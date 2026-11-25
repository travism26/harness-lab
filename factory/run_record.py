"""The last step of a Factory run: leave a Run record (docs/factory/README.md, "Run records").

A Run record is one small JSON object, `schema: 1`, with facts and numbers and no model
text (`factory/record.py`). This step writes it to <out>/run.json and appends it, as a hidden
`<!-- factory:run {...} -->` marker on the last line, to the comment the run already posted
(docs/adr/0010-run-records-live-in-comment-markers.md).

  write   (App token) runs after the agent step started, whatever happened. All four
          workflows call it with their own `--workflow`: this module writes the Implement,
          Rework and research records (`.github/workflows/research.yml`, whose record goes on
          the Ticket the way Implement's does), `factory.run_record_review` the Review record.

The step holds the App token and the agent could write anything into --out, so it trusts
nothing there. It takes the run's identity from its own arguments (the workflow's context).
From <out>/result.json it copies only known number fields and checks each one's type. A
field that fails its check is written as null with a workflow warning, and the marker is
still posted. The comment it edits is found among the bot's own comments on the Ticket,
never from a file in --out.
"""

import argparse
import json
import sys
from pathlib import Path

from factory.github import GitHub, GitHubError, label_names
from factory.record import (
    RECORDED,
    Outcomes,
    RunContext,
    bot_comments,
    build_record,
    failure_reason,
    leave_record,
    opened_pr,
    read_check,
    read_numbers,
)
from factory.review_pr import rework_round
from factory.run_record_review import write_review
from factory.ticket import OPENED_PREFIX, UNCHANGED_FILE, failed_prefix


def _outcomes(args) -> Outcomes:
    return Outcomes(
        args.job_status, args.agent_outcome, args.verify_outcome, args.publish_outcome
    )


def _head_sha(gh: GitHub, repo: str, pr: int) -> str | None:
    try:
        return gh.pr(repo, pr).get("headRefOid")
    except GitHubError as e:
        print(f"::warning title=Run record::could not read the pull request: {e}")
        return None


def _run_comment(comments: list[dict], app_slug: str, prefix: str) -> dict | None:
    """The newest comment by the factory bot that starts with `prefix` and holds no record."""
    found = [
        c for c in bot_comments(comments, app_slug) if c["body"].startswith(prefix)
    ]
    return max(found, key=lambda c: c["id"]) if found else None


def _event_round(pr_labels: str | None) -> int | None:
    """The `rework:N` the pull request carried when the run started, or None."""
    try:
        labels = json.loads(pr_labels or "[]")
    except ValueError:
        return None
    if not isinstance(labels, list):
        return None
    return rework_round([x for x in labels if isinstance(x, str)]) or None


def _live_round(gh: GitHub, repo: str, pr: int) -> int | None:
    """The `rework:N` the pull request carries now, for a run whose event labels had none."""
    try:
        return rework_round(label_names(gh.pr(repo, pr))) or None
    except GitHubError as e:
        print(
            f"::warning title=Run record::could not read the pull request's labels: {e}"
        )
        return None


def write_rework(args, gh: GitHub, out: Path) -> int:
    """The Rework run: write <out>/run.json and post one plain line, with the marker on the
    next, on the pull request. The pull request and round come from the workflow's context;
    a round the event's labels do not hold is read from the pull request."""
    numbers = read_numbers(out)
    check, touched_check = read_check(out)
    ok = args.publish_outcome == "success" and args.job_status != "cancelled"
    round_ = _event_round(args.pr_labels)
    if round_ is None:
        round_ = _live_round(gh, args.repo, args.pr)
    reason = (
        None
        if ok
        else failure_reason(_outcomes(args), numbers, (out / UNCHANGED_FILE).is_file())
    )
    head_sha = _head_sha(gh, args.repo, args.pr) if ok else None
    record = build_record(
        "rework",
        RunContext.from_args(args, args.issue),
        numbers,
        "ok" if ok else "fail",
        reason,
        pr=args.pr,
        head_sha=head_sha,
        round_=round_,
        check=check,
        touched_check=touched_check,
    )
    label = f"Rework round {'unknown' if record['round'] is None else record['round']}"
    if record["outcome"] == "ok":
        said = f"{label} pushed `{(record['head_sha'] or 'unknown')[:7]}`."
    else:
        said = f"{label} failed: `{record['reason'] or 'unknown'}`."
    leave_record(gh, args.repo, args.pr, out, record, f"{said} [Run]({args.run_url})")
    return 0


def write_implement(args, gh: GitHub, out: Path, workflow: str = "implement") -> int:
    """The Implement run, and the research run, which leaves the same comments: the marker goes
    on the comment the run posted on the Ticket, the "opened a draft PR" comment or the "failed"
    one, or on a one-line comment when it posted none (a cancelled run)."""
    numbers = read_numbers(out)
    # The research run has its own check and leaves both fields null.
    check, touched_check = read_check(out) if workflow == "implement" else (None, None)
    ok = args.publish_outcome == "success" and args.job_status != "cancelled"
    prefix = OPENED_PREFIX if ok else failed_prefix(args.run_url)
    pr = head_sha = target = None
    try:
        target = _run_comment(
            gh.pr_comments(args.repo, args.issue), args.app_slug, prefix
        )
    except GitHubError as e:
        print(f"::warning title=Run record::could not read the Ticket's comments: {e}")
    if ok and target:
        pr = opened_pr(target["body"], args.repo, OPENED_PREFIX)
        head_sha = _head_sha(gh, args.repo, pr) if pr else None
    reason = (
        None
        if ok
        else failure_reason(_outcomes(args), numbers, (out / UNCHANGED_FILE).is_file())
    )
    record = build_record(
        workflow,
        RunContext.from_args(args, args.issue),
        numbers,
        "ok" if ok else "fail",
        reason,
        pr=pr,
        head_sha=head_sha,
        round_=0,
        check=check,
        touched_check=touched_check,
    )
    leave_record(
        gh,
        args.repo,
        args.issue,
        out,
        record,
        f"The factory run for this Ticket ended: [run]({args.run_url}).",
        target,
    )
    return 0


def write(args, gh: GitHub | None = None) -> int:
    """Build the record, write <out>/run.json and put the marker on the run's comment."""
    gh = gh or GitHub()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.workflow == "review":
        return write_review(args, gh)
    if args.workflow == "rework":
        return write_rework(args, gh, out)
    return write_implement(args, gh, out, args.workflow)


def issue_arg(text: str) -> int | None:
    """`--issue`, or nothing when the run has no Ticket: a pull request that closes none, or a
    head branch that is not `factory/issue-<N>` (the workflow passes what is left of it)."""
    return int(text) if text.isascii() and text.isdigit() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="step", required=True)
    w = sub.add_parser("write")
    w.add_argument("--workflow", choices=RECORDED, required=True)
    w.add_argument("--out", required=True)
    w.add_argument("--repo", required=True)
    w.add_argument("--run-id", dest="run_id", required=True)
    w.add_argument("--attempt", required=True)
    w.add_argument("--issue", type=issue_arg, default=None)
    w.add_argument("--head-sha", dest="head_sha", default="")
    w.add_argument("--project", default="")
    w.add_argument("--login", required=True)
    w.add_argument("--model", required=True)
    w.add_argument("--budget", required=True)
    w.add_argument("--claude-code-version", dest="claude_code_version", required=True)
    w.add_argument("--pr", type=int, default=None)
    w.add_argument("--pr-labels", dest="pr_labels", default=None)
    w.add_argument("--app-slug", required=True)
    w.add_argument("--run-url", required=True)
    w.add_argument("--job-status", default="")
    w.add_argument(
        "--agent-outcome",
        dest="agent_outcome",
        required=True,
        help="how the agent step ended: Implement's Build, Rework's Rework, "
        "Review's Review",
    )
    w.add_argument(
        "--verify-outcome",
        default="",
        help="how the new Project's check ended (Implement and Rework only)",
    )
    w.add_argument(
        "--publish-outcome",
        dest="publish_outcome",
        required=True,
        help="how the step that publishes the work ended: Implement's commit, "
        "push and open, Rework's commit and push, Review's post of the report",
    )
    args = parser.parse_args(argv)
    if args.project in ("null", ""):
        args.project = None
    try:
        return write(args)
    except (RuntimeError, GitHubError) as e:
        print(f"::error title=Factory run record failed::{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
