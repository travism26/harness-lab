"""Make a repo's labels match the factory's label set (factory/labels.json).

Usage:
  uv run python -m factory.sync_labels                # dry run against origin's repo
  uv run python -m factory.sync_labels --repo O/R     # dry run against another repo
  uv run python -m factory.sync_labels --apply        # create and update for real

A dry run reads the repo's labels and prints what --apply would do; it writes
nothing. --apply renames a label whose old name is in the file and whose new
name is not, with `gh label edit <old> --name <new>`, and it does not also
create that name. When both names exist it does not delete: it updates the new
name in place if the colour or description differs, and it says the old name is
left. When only the new name exists it plans nothing for that pair. It creates
each other missing label and corrects the colour and description of each one
that differs. It never deletes a label, so labels outside the set, including
`ready-for-factory`, are left alone. GitHub label names are case-insensitive, so
`Bug` and `bug` are the same label.

Exit codes: 0 done (or nothing to do), 1 a gh call failed, 2 bad usage.
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

LABELS_FILE = Path(__file__).resolve().parent / "labels.json"


@dataclass(frozen=True)
class Label:
    name: str
    color: str
    description: str


@dataclass(frozen=True)
class Change:
    action: str  # "create", "update", "rename", or "leave"
    label: Label
    current: Label | None = None
    left: str | None = None


def load_labels(path: Path = LABELS_FILE) -> list[Label]:
    raw = json.loads(path.read_text())
    labels = [
        Label(l["name"], l["color"].lower().lstrip("#"), l["description"])
        for l in raw["labels"]
    ]
    names = [l.name.lower() for l in labels]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"{path} lists these labels twice: {', '.join(duplicates)}")
    return labels


def load_renames(path: Path = LABELS_FILE) -> list[tuple[str, str]]:
    raw = json.loads(path.read_text())
    return [(item["old"], item["new"]) for item in raw.get("renames", [])]


def _differs(current: Label, label: Label) -> bool:
    return (current.color.lower(), current.description) != (
        label.color,
        label.description,
    )


def plan_changes(
    desired: list[Label],
    existing: list[Label],
    renames: Sequence[tuple[str, str]] | None = None,
) -> list[Change]:
    """What --apply must do to make existing hold every desired label.

    A rename is one edit of the old name. It is not also a create, and it is
    never a delete. `ready-for-factory` is not a rename and is not created.
    """
    by_name = {label.name.lower(): label for label in existing}
    desired_by = {label.name.lower(): label for label in desired}
    changes: list[Change] = []
    renamed: set[str] = set()
    for old, new in renames or ():
        wanted = desired_by.get(new.lower())
        if wanted is None:
            continue
        old_label = by_name.get(old.lower())
        new_label = by_name.get(new.lower())
        if old_label is not None and new_label is None:
            changes.append(Change("rename", wanted, old_label))
            renamed.add(new.lower())
        elif old_label is not None and new_label is not None:
            renamed.add(new.lower())
            if _differs(new_label, wanted):
                changes.append(Change("update", wanted, new_label, left=old_label.name))
            else:
                changes.append(Change("leave", wanted, old_label))
    for label in desired:
        if label.name.lower() in renamed:
            continue
        current = by_name.get(label.name.lower())
        if current is None:
            changes.append(Change("create", label))
        elif _differs(current, label):
            changes.append(Change("update", label, current))
    return changes


def _gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def origin_repo() -> str | None:
    r = _gh(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def existing_labels(repo: str) -> list[Label]:
    r = _gh(
        [
            "label",
            "list",
            "-R",
            repo,
            "--limit",
            "1000",
            "--json",
            "name,color,description",
        ]
    )
    if r.returncode != 0:
        raise RuntimeError(f"could not list the labels of {repo}: {r.stderr.strip()}")
    return [
        Label(l["name"], l["color"], l.get("description") or "")
        for l in json.loads(r.stdout)
    ]


def command_for(change: Change, repo: str) -> list[str]:
    if change.action == "leave":
        raise ValueError("a leave change is not a gh command")
    # `edit` addresses the label by the name it already has on the repo.
    # A rename passes `--name` and does not also create the new name.
    name = change.current.name if change.current else change.label.name
    verb = "create" if change.action == "create" else "edit"
    command = [
        "label",
        verb,
        name,
        "-R",
        repo,
        "--color",
        change.label.color,
        "--description",
        change.label.description,
    ]
    if change.action == "rename":
        command.extend(["--name", change.label.name])
    return command


def describe(change: Change) -> str:
    if change.action == "create":
        return (
            f"create  {change.label.name}  #{change.label.color}  "
            f"{change.label.description}"
        )
    cur = change.current
    assert cur is not None, "an update, rename, or leave carries the current label"
    if change.action == "rename":
        return (
            f"rename  {cur.name} -> {change.label.name}  "
            f"#{change.label.color}  {change.label.description}"
        )
    if change.action == "leave":
        return f"leave  {cur.name}  both names exist; the old name is left"
    diffs = []
    if cur.color.lower() != change.label.color:
        diffs.append(f"colour #{cur.color} -> #{change.label.color}")
    if cur.description != change.label.description:
        diffs.append(f"description {cur.description!r} -> {change.label.description!r}")
    text = f"update  {cur.name}  " + "; ".join(diffs)
    if change.left:
        text += f"; {change.left} is left"
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="owner/name (default: the current clone's repo)")
    parser.add_argument(
        "--apply", action="store_true", help="make the changes (default: dry run)"
    )
    args = parser.parse_args(argv)

    desired = load_labels()
    repo = args.repo or origin_repo()
    if not repo:
        print(
            "Error: no --repo given and `gh repo view` found no repo here",
            file=sys.stderr,
        )
        return 2
    try:
        changes = plan_changes(desired, existing_labels(repo), load_renames())
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
    applied = [change for change in changes if change.action != "leave"]
    for change in applied:
        r = _gh(command_for(change, repo))
        if r.returncode != 0:
            failed += 1
            print(
                f"FAILED {change.action} {change.label.name}: {r.stderr.strip()}",
                file=sys.stderr,
            )
    if failed:
        print(f"{failed} of {len(applied)} changes failed", file=sys.stderr)
        return 1
    print("Labels match the set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
