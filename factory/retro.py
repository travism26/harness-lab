"""Print one Markdown report on the pull requests merged since the last Retro.

Reads GitHub through `gh` (or a fixtures directory) and makes no model call and no write. The
owner starts a local agent session that reads the report and drafts one `retro` issue
(docs/factory/README.md, "Running a retro").

Usage:
  uv run python -m factory.retro --repo O/R [--since DATE] [--app-slug S]
  uv run python -m factory.retro --fixtures DIR [--repo O/R] [--since DATE]
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from factory.collect_findings import findings_in, neutralize, review_for_head
from factory.github import GitHub, GitHubError
from factory.metrics import Facts
from factory.override import parse_override
from factory.record import TOKEN_RE
from factory.review_pr import SPEC_KINDS, review_verdict
from factory.switch_rule import default_app_slug

LABEL = "retro"
STANDARDS_LABEL = "standards-findings"
DUE_AT = 10
FIXTURES_REPO = "travism26/harness-lab"
REDACTED = "[redacted]"


class RetroError(RuntimeError):
    pass


class FixtureSource:
    """Facts read from a fixtures directory: `pr-<N>/{pr,pr-comments,pr-commits}.json`, and
    optionally `retro-issues.json` and `standards-findings.json`."""

    def __init__(self, directory: Path):
        if not directory.is_dir():
            raise RetroError(f"{directory} is not a directory")
        self.directory = directory

    def _json(self, path: Path, default: Any) -> Any:
        return json.loads(path.read_text()) if path.is_file() else default

    def last_retro(self) -> str | None:
        issues = self._json(self.directory / "retro-issues.json", [])
        return max((i["createdAt"] for i in issues), default=None)

    def merged_prs(self) -> list[dict]:
        return [
            json.loads(p.read_text())
            for p in sorted(self.directory.glob("pr-*/pr.json"))
        ]

    def comments(self, pr: int) -> list[dict]:
        return self._json(self.directory / f"pr-{pr}" / "pr-comments.json", [])

    def commits(self, pr: int) -> list[dict]:
        return self._json(self.directory / f"pr-{pr}" / "pr-commits.json", [])

    def standards_issue(self) -> dict | None:
        return self._json(self.directory / "standards-findings.json", None)


class LiveSource:
    def __init__(self, gh: Any, repo: str):
        self.gh, self.repo = gh, repo

    def last_retro(self) -> str | None:
        return self.gh.newest_issue_created(self.repo, LABEL)

    def merged_prs(self) -> list[dict]:
        return self.gh.merged_prs(self.repo)

    def comments(self, pr: int) -> list[dict]:
        return self.gh.pr_comments(self.repo, pr)

    def commits(self, pr: int) -> list[dict]:
        return self.gh.pull_commits(self.repo, pr)

    def standards_issue(self) -> dict | None:
        issues = self.gh.open_issues_labelled(self.repo, STANDARDS_LABEL)
        if not issues:
            return None
        number = min(issues)
        issue = self.gh.issue(self.repo, number)
        return {
            "number": number,
            "body": issue.get("body") or "",
            "comments": self.gh.pr_comments(self.repo, number),
        }


def _when(text: str) -> datetime:
    """An ISO date or timestamp, read as UTC when it names no zone."""
    when = datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def _owner_override(comments: Sequence[dict], owner: str) -> str | None:
    """The reason in the owner's last `Override:` comment. Only the repo owner's counts, as in
    the Override workflow."""
    found = None
    for comment in comments:
        if ((comment.get("user") or {}).get("login") or "").lower() != owner.lower():
            continue
        reason = parse_override(comment.get("body") or "")
        if reason:
            found = reason
    return found


def _bullets(lines: Sequence[str]) -> str:
    return "\n".join(lines) if lines else "none"


def build(source: Any, repo: str, app_slug: str, since: str | None) -> str:
    start = _when(since or source.last_retro() or "1970-01-01")
    owner = repo.split("/")[0]
    merged = [
        pr
        for pr in source.merged_prs()
        if pr.get("mergedAt") and _when(pr["mergedAt"]) > start
    ]
    merged.sort(key=lambda pr: pr["number"])
    blocked: list[str] = []
    overrides: list[str] = []
    blocking: list[str] = []
    owner_commits: list[str] = []
    for pr in merged:
        n, title = pr["number"], neutralize(pr.get("title") or "").strip()
        comments = source.comments(n)
        review = review_for_head(
            comments, pr.get("headRefOid") or "", f"{app_slug}[bot]"
        )
        reason = _owner_override(comments, owner)
        is_blocked = review is not None and review_verdict(review) == "BLOCKED"
        if is_blocked:
            blocked.append(f"- #{n} {title}")
        if reason:
            overrides.append(f"- #{n} {title}: {neutralize(reason)}")
        if (is_blocked or reason) and review:
            for kind, description, path, fix in findings_in(
                review, "Spec", [k for k, blocks in SPEC_KINDS.items() if blocks]
            ):
                where = f" (`{neutralize(path)}`)" if path else ""
                blocking.append(
                    f"- #{n} **{kind}** {neutralize(description)}{where}. "
                    f"Fix: {neutralize(fix)}"
                )
        if (pr.get("headRefName") or "").startswith("factory/"):
            count = Facts(app_slug, commits=source.commits(n)).owner_commits
            if count:
                owner_commits.append(
                    f"- #{n}: {count} owner commit{'s' if count != 1 else ''}"
                )
    issue = source.standards_issue()
    standing = "none"
    if issue:
        parts = [issue.get("body") or ""] + [
            c.get("body") or "" for c in issue.get("comments") or []
        ]
        standing = f"Issue #{int(issue['number'])}\n\n" + "\n".join(
            neutralize(p).strip() for p in parts if p.strip()
        )
    lines = [
        "# Retro report",
        "",
        f"Repo: {repo}",
        f"Since: {start.date().isoformat()}",
        f"Merged since the last Retro: {len(merged)}",
        f"Retro due: {'yes' if len(merged) >= DUE_AT else 'no'}",
        "",
        "## Merged on a BLOCKED head",
        _bullets(blocked),
        "",
        "## Merged with an Override",
        _bullets(overrides),
        "",
        "## Blocking findings",
        _bullets(blocking),
        "",
        "## Owner commits before merge",
        _bullets(owner_commits),
        "",
        "## Standards findings",
        standing,
        "",
        "## Post-merge hand-fixes",
        "",
    ]
    return TOKEN_RE.sub(REDACTED, "\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    group = parser.add_argument_group("source")
    group.add_argument("--repo", help="for example travism26/harness-lab")
    group.add_argument("--fixtures", help="read a fixtures directory instead of GitHub")
    parser.add_argument("--since", help="a date; default: the newest `retro` issue")
    parser.add_argument("--app-slug", default=None, help="default OWNER-factory")
    args = parser.parse_args(argv)
    if not args.repo and not args.fixtures:
        parser.error("one of --repo or --fixtures is required")
    repo = args.repo or FIXTURES_REPO
    try:
        source: FixtureSource | LiveSource = (
            FixtureSource(Path(args.fixtures))
            if args.fixtures
            else LiveSource(GitHub(), repo)
        )
        report = build(
            source, repo, args.app_slug or default_app_slug(repo), args.since
        )
    except (RetroError, GitHubError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
