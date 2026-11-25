"""Which Ticket the factory starts, and the job that adds `factory:start`.

`pick` is pure: it reads issues the caller already has and does not call GitHub.
The workflow (`.github/workflows/picker.yml`) reads with the workflow token and
mints the App token only when the decision is to add `factory:start` or to drop
a lock that a closed Ticket still holds. It does not call factory-preflight.

Usage:
  uv run python -m factory.picker plan --repo O/R --out plan.json
  uv run python -m factory.picker apply --repo O/R --out plan.json
  uv run python -m factory.picker retry --repo O/R --issue N
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from factory.github import GitHub, GitHubError, label_names, write_comment
from factory.ticket import FAILED_LABELS, LOCK_LABELS, PROGRESS_LABELS, START_LABEL

APPROVAL_LABELS = ("owner:implement", "ready-for-implementation")
SPEC_LABELS = ("builder:spec-ready", "spec:ready-for-review")
READY_LABEL = "ready-for-agent"
VIEW = "number,state,labels,parent,subIssues,blockedBy"
RETRY_PREFIX = "Retry:"


@dataclass(frozen=True)
class Blocker:
    number: int
    state: str


@dataclass(frozen=True)
class Candidate:
    number: int
    state: str = "OPEN"
    labels: tuple[str, ...] = ()
    blockers: tuple[Blocker, ...] = ()
    parent: int | None = None
    sub_issues: tuple[int, ...] = ()


@dataclass(frozen=True)
class Choice:
    issue: int | None
    reason: str
    spec: int | None = None


def _has(labels: Sequence[str], names: Sequence[str]) -> bool:
    return any(label in names for label in labels)


def _open(state: str) -> bool:
    return state.upper() == "OPEN"


def lock_held(issues: Sequence[Candidate]) -> bool:
    """The global lock: an open issue wears the progress label or factory:start."""
    return any(
        _open(issue.state) and _has(issue.labels, LOCK_LABELS) for issue in issues
    )


def is_spec(issue: Candidate) -> bool:
    return _has(issue.labels, SPEC_LABELS) or bool(issue.sub_issues)


def approved(issue: Candidate) -> bool:
    return _open(issue.state) and _has(issue.labels, APPROVAL_LABELS)


def _open_blocker(issue: Candidate) -> bool:
    return any(_open(blocker.state) for blocker in issue.blockers)


def _already_started(issue: Candidate) -> bool:
    return _has(issue.labels, PROGRESS_LABELS) or START_LABEL in issue.labels


def eligible_child(issue: Candidate) -> bool:
    return (
        _open(issue.state)
        and READY_LABEL in issue.labels
        and not _has(issue.labels, FAILED_LABELS)
        and not _already_started(issue)
        and not _open_blocker(issue)
    )


def eligible_hand(issue: Candidate) -> bool:
    """A hand Ticket is the approved issue itself. It needs no ready-for-agent."""
    return (
        _open(issue.state)
        and not _has(issue.labels, FAILED_LABELS)
        and not _already_started(issue)
        and not _open_blocker(issue)
    )


def pick(issues: Sequence[Candidate]) -> Choice:
    """The lowest eligible Ticket across every approved issue, or why there is none."""
    if lock_held(issues):
        return Choice(None, "lock held")
    approved_issues = [issue for issue in issues if approved(issue)]
    if not approved_issues:
        return Choice(None, "no approval")
    chosen: list[tuple[int, int | None]] = []
    for issue in approved_issues:
        if is_spec(issue):
            for child in issues:
                if child.parent == issue.number and eligible_child(child):
                    chosen.append((child.number, issue.number))
        elif eligible_hand(issue):
            chosen.append((issue.number, None))
    if not chosen:
        return Choice(None, "none eligible")
    number, spec = min(chosen)
    return Choice(number, "selected", spec)


def _names(item: dict) -> tuple[str, ...]:
    labels = item.get("labels") or []
    return tuple(
        label["name"] if isinstance(label, dict) else str(label) for label in labels
    )


def _candidate(item: dict) -> Candidate:
    parent = item.get("parent") or {}
    blockers = (item.get("blockedBy") or {}).get("nodes") or []
    children = (item.get("subIssues") or {}).get("nodes") or []
    return Candidate(
        number=int(item["number"]),
        state=item.get("state") or "OPEN",
        labels=_names(item),
        blockers=tuple(
            Blocker(int(node["number"]), node.get("state") or "") for node in blockers
        ),
        parent=int(parent["number"]) if parent.get("number") else None,
        sub_issues=tuple(int(node["number"]) for node in children),
    )


def load_open(gh: GitHub, repo: str) -> list[Candidate]:
    """Open approved issues, their children, and any open issue holding the lock."""
    numbers: set[int] = set()
    for label in (*APPROVAL_LABELS, *LOCK_LABELS):
        try:
            numbers.update(gh.open_issues_labelled(repo, label))
        except GitHubError:
            continue
    viewed: dict[int, dict] = {}
    for number in sorted(numbers):
        viewed[number] = gh.issue_fields(repo, number, VIEW)
    extra = [
        int(node["number"])
        for item in viewed.values()
        for node in (item.get("subIssues") or {}).get("nodes") or []
    ]
    for number in extra:
        if number not in viewed:
            viewed[number] = gh.issue_fields(repo, number, VIEW)
    return [_candidate(item) for item in viewed.values()]


def _post(gh: GitHub, repo: str, number: int, body: str) -> None:
    with TemporaryDirectory() as tmp:
        gh.comment(repo, number, write_comment(Path(tmp), "comment.md", body))


def _start_comment(number: int) -> str:
    return f"Approved. The factory will start #{number}.\n"


def _refusal(reason: str) -> str:
    if reason == "lock held":
        return "This is approved. The lock is held, so no Ticket was started.\n"
    if reason == "none eligible":
        return "This is approved. No Ticket is eligible.\n"
    return "This issue is not approved, so nothing starts.\n"


def _plan(
    choice: Choice,
    *,
    drop_lock: bool = False,
    drop_issue: int | None = None,
    comment_issue: int | None = None,
) -> dict:
    if choice.issue is not None:
        target = choice.spec if choice.spec is not None else choice.issue
        return {
            "start": choice.issue,
            "drop_lock": drop_lock,
            "drop_issue": drop_issue,
            "comment_on": target,
            "comment": _start_comment(choice.issue),
            "reason": "selected",
        }
    comment = _refusal(choice.reason) if comment_issue is not None else ""
    return {
        "start": None,
        "drop_lock": drop_lock,
        "drop_issue": drop_issue,
        "comment_on": comment_issue,
        "comment": comment,
        "reason": choice.reason,
    }


def decide(
    gh: GitHub,
    repo: str,
    *,
    event: str,
    action: str,
    label: str,
    issue: int | None,
    spec: str,
    issue_labels: Sequence[str],
) -> dict:
    """The plan for one picker trigger. A refusal comment is posted by `plan`."""
    if event == "issues" and action == "closed":
        # A green settle already dropped the lock. The close still plans, so a
        # Ticket this one blocked can start. Drop a lock only when this issue
        # still wears one: that is the only close that needs the App token
        # without also starting a Ticket.
        holds_lock = _has(issue_labels, LOCK_LABELS)
        choice = pick(load_open(gh, repo))
        # The closed Ticket is not an open candidate. Say why on it only when
        # nothing starts and it still held the lock; a start comments on the
        # Ticket that is starting.
        comment_issue = issue if choice.issue is None and holds_lock else None
        return _plan(
            choice,
            drop_lock=holds_lock,
            drop_issue=issue if holds_lock else None,
            comment_issue=comment_issue,
        )
    if event == "workflow_dispatch":
        number = int(spec)
        item = gh.issue_fields(repo, number, VIEW)
        target = _candidate(item)
        if not approved(target):
            return _plan(Choice(None, "no approval"), comment_issue=number)
        return _plan(pick(load_open(gh, repo)), comment_issue=number)
    issues = load_open(gh, repo)
    if label == READY_LABEL and not any(approved(item) for item in issues):
        return _plan(Choice(None, "no approval"))
    comment_issue = issue if label in APPROVAL_LABELS else None
    choice = pick(issues)
    if choice.issue is None and label == READY_LABEL:
        comment_issue = None
    return _plan(choice, comment_issue=comment_issue)


def queue_next(gh: GitHub, repo: str, run_url: str = "") -> int | None:
    """After the lock drops, add factory:start to the next eligible Ticket.

    Fakes that cannot read issue fields do nothing. The CI gate and Implement's
    failure path already hold the App token.
    """
    if not hasattr(gh, "issue_fields"):
        return None
    choice = pick(load_open(gh, repo))
    if choice.issue is None:
        return None
    gh.add_labels(repo, choice.issue, (START_LABEL,))
    target = choice.spec if choice.spec is not None else choice.issue
    link = f" [Run]({run_url})" if run_url else ""
    _post(
        gh,
        repo,
        target,
        f"The lock is off. The factory will start #{choice.issue}.{link}\n",
    )
    return choice.issue


def apply_plan(gh: GitHub, repo: str, plan: dict) -> int:
    if plan.get("drop_lock") and plan.get("drop_issue"):
        item = gh.issue(repo, int(plan["drop_issue"]))
        present = tuple(label for label in LOCK_LABELS if label in label_names(item))
        if present:
            gh.remove_labels(repo, int(plan["drop_issue"]), present)
    if plan.get("start"):
        gh.add_labels(repo, int(plan["start"]), (START_LABEL,))
    if plan.get("comment") and plan.get("comment_on"):
        _post(gh, repo, int(plan["comment_on"]), plan["comment"])
    print(f"picker {plan.get('reason')}: start={plan.get('start')}")
    return 0


def retry_issue(gh: GitHub, repo: str, issue: int, body: str) -> int:
    """Clear factory:failed. Add factory:start only when the lock is free."""
    lines = (body or "").splitlines()
    if not lines or not lines[0].startswith(RETRY_PREFIX):
        print("not a Retry: nothing to do")
        return 0
    item = gh.issue(repo, issue)
    stale = tuple(label for label in FAILED_LABELS if label in label_names(item))
    if stale:
        gh.remove_labels(repo, issue, stale)
    if hasattr(gh, "issue_fields") and lock_held(load_open(gh, repo)):
        _post(
            gh,
            repo,
            issue,
            "The lock is held, so `factory:start` was not added. "
            "This Ticket can start when the lock is free.\n",
        )
        print("retry cleared factory:failed; the lock is held")
        return 0
    gh.add_labels(repo, issue, (START_LABEL,))
    print(f"retry added {START_LABEL} on {repo}#{issue}")
    return 0


def _labels_from(raw: str) -> list[str]:
    if not raw or raw == "null":
        return []
    loaded = json.loads(raw)
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if item]


def _write_outputs(plan: dict) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    start = "" if plan.get("start") is None else str(plan["start"])
    drop = "true" if plan.get("drop_lock") else "false"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"start={start}\n")
        handle.write(f"drop={drop}\n")


def plan_main(gh: GitHub, repo: str, out: Path) -> int:
    issue_raw = os.environ.get("ISSUE") or ""
    issue = int(issue_raw) if issue_raw.isdigit() else None
    plan = decide(
        gh,
        repo,
        event=os.environ.get("EVENT") or "",
        action=os.environ.get("ACTION") or "",
        label=os.environ.get("LABEL") or "",
        issue=issue,
        spec=os.environ.get("SPEC") or "",
        issue_labels=_labels_from(os.environ.get("ISSUE_LABELS") or ""),
    )
    # A refusal is posted with the workflow token. Adding factory:start waits
    # for the App token in `apply`.
    if plan["comment"] and not plan["start"] and not plan["drop_lock"]:
        if plan["comment_on"]:
            _post(gh, repo, int(plan["comment_on"]), plan["comment"])
        plan["comment"] = ""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan) + "\n")
    _write_outputs(plan)
    print(f"picker plan: {plan['reason']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="step", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--repo", required=True)
    plan.add_argument("--out", required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("--repo", required=True)
    apply.add_argument("--out", required=True)
    retry = sub.add_parser("retry")
    retry.add_argument("--repo", required=True)
    retry.add_argument("--issue", type=int, required=True)
    args = parser.parse_args(argv)
    gh = GitHub()
    if args.step == "plan":
        return plan_main(gh, args.repo, Path(args.out))
    if args.step == "apply":
        return apply_plan(gh, args.repo, json.loads(Path(args.out).read_text()))
    return retry_issue(gh, args.repo, args.issue, os.environ.get("BODY") or "")


if __name__ == "__main__":
    sys.exit(main())
