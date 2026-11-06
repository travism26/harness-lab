"""Make a repo's labels match the factory's label set (factory/labels.json).

Usage:
  uv run python -m factory.sync_labels                # dry run against origin's repo
  uv run python -m factory.sync_labels --repo O/R     # dry run against another repo
  uv run python -m factory.sync_labels --apply        # create and update for real

A dry run reads the repo's labels and prints what --apply would do; it writes
nothing. --apply creates each missing label and corrects the colour and
description of each one that differs. It never deletes a label, so labels
outside the set are left alone. GitHub label names are case-insensitive, so
`Bug` and `bug` are the same label.

Exit codes: 0 done (or nothing to do), 1 a gh call failed, 2 bad usage.
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

LABELS_FILE = Path(__file__).resolve().parent / "labels.json"


@dataclass(frozen=True)
class Label:
    name: str
    color: str
    description: str


@dataclass(frozen=True)
class Change:
    action: str  # "create" or "update"
    label: Label
    current: Optional[Label] = None


def load_labels(path: Path = LABELS_FILE) -> List[Label]:
    raw = json.loads(path.read_text())
    labels = [Label(l["name"], l["color"].lower().lstrip("#"), l["description"])
              for l in raw["labels"]]
    names = [l.name.lower() for l in labels]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"{path} lists these labels twice: {', '.join(duplicates)}")
    return labels


def plan_changes(desired: List[Label], existing: List[Label]) -> List[Change]:
    """What --apply must do to make existing hold every desired label."""
    by_name = {l.name.lower(): l for l in existing}
    changes = []
    for label in desired:
        current = by_name.get(label.name.lower())
        if current is None:
            changes.append(Change("create", label))
        elif (current.color.lower(), current.description) != (label.color, label.description):
            changes.append(Change("update", label, current))
    return changes


def _gh(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def origin_repo() -> Optional[str]:
    r = _gh(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def existing_labels(repo: str) -> List[Label]:
    r = _gh(["label", "list", "-R", repo, "--limit", "1000",
             "--json", "name,color,description"])
    if r.returncode != 0:
        raise RuntimeError(f"could not list the labels of {repo}: {r.stderr.strip()}")
    return [Label(l["name"], l["color"], l.get("description") or "")
            for l in json.loads(r.stdout)]


def command_for(change: Change, repo: str) -> List[str]:
    verb = "create" if change.action == "create" else "edit"
    # `edit` addresses the label by the name it already has on the repo.
    name = change.current.name if change.current else change.label.name
    return ["label", verb, name, "-R", repo, "--color", change.label.color,
            "--description", change.label.description]


def describe(change: Change) -> str:
    if change.action == "create":
        return f"create  {change.label.name}  #{change.label.color}  {change.label.description}"
    cur = change.current
    diffs = []
    if cur.color.lower() != change.label.color:
        diffs.append(f"colour #{cur.color} -> #{change.label.color}")
    if cur.description != change.label.description:
        diffs.append(f"description {cur.description!r} -> {change.label.description!r}")
    return f"update  {cur.name}  " + "; ".join(diffs)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="owner/name (default: the current clone's repo)")
    parser.add_argument("--apply", action="store_true", help="make the changes (default: dry run)")
    args = parser.parse_args(argv)

    desired = load_labels()
    repo = args.repo or origin_repo()
    if not repo:
        print("Error: no --repo given and `gh repo view` found no repo here", file=sys.stderr)
        return 2
    try:
        changes = plan_changes(desired, existing_labels(repo))
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    mode = "APPLY" if args.apply else "DRY RUN (nothing is written; pass --apply)"
    print(f"{mode}: {repo}, {len(desired)} labels in the set, {len(changes)} to change")
    for change in changes:
        print(f"  {describe(change)}")
    if not args.apply:
        return 0

    failed = 0
    for change in changes:
        r = _gh(command_for(change, repo))
        if r.returncode != 0:
            failed += 1
            print(f"FAILED {change.action} {change.label.name}: {r.stderr.strip()}", file=sys.stderr)
    if failed:
        print(f"{failed} of {len(changes)} changes failed", file=sys.stderr)
        return 1
    print("Labels match the set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
