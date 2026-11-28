"""The factory's write-only recorder: one comment per event on the open `Factory signals` issue.

Nothing reads the issue yet. The pure functions here build the comment (`entry`), tell whether it
is already written (`already`) and choose where it goes (`destination`). `write` does the
GitHub calls, best-effort: a `GitHubError` is printed as a warning and never reaches the step.

Each Friday .github/workflows/close-signals.yml runs this module: `close_week` comments on every
open issue (`close_targets`) that the week is closed, then closes it. There a `GitHubError`
fails the job.
"""

import argparse
import os
import re
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from factory.github import REDACTED, GitHub, GitHubError, neutralize, write_comment
from factory.switch_rule import default_app_slug, is_factory_app

LABEL = "factory:signals"
ISSUE_TITLE = "Factory signals"
ISSUE_BODY = (
    "One comment per factory event (an Implement or Rework failure, a `Retry:`). "
    "Nothing acts on them automatically. A job closes this issue every Friday; "
    "the next event opens a new one.\n"
)
CLOSED_COMMENT = (
    "The week is closed. The next factory event opens a new `Factory signals` issue.\n"
)
TEXT_MAX_CHARS = 500
NONE = "none"

IMPLEMENT_FAILED = "implement-failed"
REWORK_FAILED = "rework-failed"
RETRY = "retry"

_TOKEN_RE = re.compile(
    r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{8,}"
    r"|github_pat_[A-Za-z0-9_]{8,}"
    r"|x-access-token:[^\s@]+"
    r"|sk-(?:ant|or)-[A-Za-z0-9_\-]{8,}"
)
_KEY_BAD_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def marker(key: str) -> str:
    return f"<!-- factory:signal {_KEY_BAD_RE.sub('-', str(key))} -->"


def clean_text(text: str) -> str:
    """Untrusted text for the Text field: redacted, neutralized, one line, capped."""
    text = _TOKEN_RE.sub(REDACTED, text or "")
    text = " ".join(neutralize(text).split())
    if len(text) > TEXT_MAX_CHARS:
        text = text[: TEXT_MAX_CHARS - 1].rstrip() + "…"
    return text or NONE


def entry(event: dict) -> tuple[str, str]:
    """(marker, comment) for an event with `kind`, `key`, and optional `ticket`, `pr`, `run`,
    `text`. Every field is neutralized; the marker is the first line."""
    mark = marker(event["key"])

    def field(name: str, value: Any) -> str:
        shown = clean_text(str(value)) if value not in (None, "") else NONE
        return f"- {name}: {shown}"

    lines = [
        mark,
        field("Kind", event["kind"]),
        field("Ticket", f"#{event['ticket']}" if event.get("ticket") else None),
        field("Pull request", f"#{event['pr']}" if event.get("pr") else None),
        field("Run", event.get("run")),
        field("Text", event.get("text")),
    ]
    return mark, "\n".join(lines) + "\n"


def already(comments: Iterable[dict], mark: str, app_slug: str) -> bool:
    """Whether a comment by the factory App starts with this marker."""
    return any(
        (c.get("body") or "").startswith(mark)
        and is_factory_app(((c.get("user") or {}).get("login")) or "", app_slug)
        for c in comments or ()
    )


def destination(open_issue_numbers: Sequence[int]) -> tuple[str, int | None]:
    """`("create", None)` with no open signal issue, else `("append", lowest number)`."""
    if not open_issue_numbers:
        return ("create", None)
    return ("append", min(open_issue_numbers))


def close_targets(open_issue_numbers: Sequence[int]) -> list[int]:
    """Every open signal issue, lowest number first."""
    return sorted(open_issue_numbers)


def run_id(run_url: str = "") -> str:
    found = os.environ.get("GITHUB_RUN_ID") or ""
    if found.isdigit():
        return found
    match = re.search(r"/runs/(\d+)", run_url or "")
    return match.group(1) if match else ""


def env_run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL") or ""
    repo = os.environ.get("GITHUB_REPOSITORY") or ""
    rid = os.environ.get("GITHUB_RUN_ID") or ""
    return f"{server}/{repo}/actions/runs/{rid}" if server and repo and rid else ""


def write(gh: Any, repo: str, event: dict, app_slug: str = "") -> None:
    """Append the event once. Never raises a `GitHubError`: it prints a warning instead."""
    try:
        mark, comment = entry(event)
        action, issue = destination(gh.open_issues_labelled(repo, LABEL))
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            if issue is None:
                issue = gh.create_issue(
                    repo,
                    ISSUE_TITLE,
                    write_comment(out, "issue.md", ISSUE_BODY),
                    (LABEL,),
                )
            elif already(
                gh.pr_comments(repo, issue), mark, app_slug or default_app_slug(repo)
            ):
                print(f"signal {mark} already on #{issue}")
                return
            gh.comment(repo, issue, write_comment(out, "signal.md", comment))
        print(f"signal {event['kind']} written to #{issue} ({action})")
    except GitHubError as e:
        print(f"warning: could not record the {event.get('kind')} signal: {e}")


def close_week(gh: Any, repo: str) -> list[int]:
    """Comment on, then close, each open signal issue. A `GitHubError` is not swallowed."""
    closed: list[int] = []
    with TemporaryDirectory() as tmp:
        out = Path(tmp)
        for number in close_targets(gh.open_issues_labelled(repo, LABEL)):
            gh.comment(repo, number, write_comment(out, "closed.md", CLOSED_COMMENT))
            gh.close_issue(repo, number)
            closed.append(number)
    return closed


def main(argv: list[str] | None = None, gh: Any | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Close the week's Factory signals issues."
    )
    parser.add_argument("--repo", required=True)
    args = parser.parse_args(argv)
    try:
        closed = close_week(gh or GitHub(), args.repo)
    except GitHubError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if closed:
        print("closed " + ", ".join(f"#{n}" for n in closed))
    else:
        print("no open Factory signals issue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
