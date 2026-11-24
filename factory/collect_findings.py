"""Collect the Standards Findings of a merged pull request's Review into one rolling issue.

.github/workflows/collect-findings.yml runs it when a same-repo pull request merges. No agent
runs. It reads the Review of the head that merged, keeps its `repo_standard` and
`baseline_smell` Findings (neither blocks), and appends them as one comment, headed by a hidden
marker, to the open issue labelled `standards-findings`, or opens that issue. Nothing here
labels the issue `ready-for-agent`.

Usage:
  uv run python -m factory.collect_findings --repo O/R --pr N --head SHA [--app-slug S]
"""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from factory.github import GitHub, GitHubError, neutralize_comments, write_comment
from factory.review_pr import STANDARDS_KINDS, parse_gate
from factory.switch_rule import default_app_slug, is_factory_app

LABEL = "standards-findings"
ISSUE_TITLE = "Standards findings from merged pull requests"
ISSUE_BODY = (
    "The Review's non-blocking Standards Findings (`repo_standard`, `baseline_smell`) "
    "of each merged pull request, one comment per pull request. Nothing acts on them "
    "automatically.\n"
)

_ZWSP = "\u200b"
Finding = tuple[str, str, str, str]  # kind, description, path, fix

_LINE_RE = re.compile(
    r"^- \*\*(?P<kind>[a-z_]+)\*\* (?P<desc>.*?)"
    r"(?: \(`(?P<path>[^`]*)`\))?\. Fix: (?P<fix>.*)$"
)
_HEADING_RE = re.compile(r"^###\s+(?P<name>\w+)")
_MENTION_RE = re.compile(r"@(?=\w)")
_NUMBER_RE = re.compile(r"#(?=\d)")
_ISSUE_URL_RE = re.compile(r"(/(?:issues|pull|pulls|discussions)/)(?=\d)")


def neutralize(text: str) -> str:
    """Finding text that cannot open or close an HTML comment, mention anyone, or reference
    (so close) an issue by `#N`, `owner/repo#N` or an issue URL."""
    out = neutralize_comments(text or "")
    out = _NUMBER_RE.sub("#" + _ZWSP, out)
    out = _MENTION_RE.sub("@" + _ZWSP, out)
    return _ISSUE_URL_RE.sub(lambda m: m.group(1) + _ZWSP, out)


def marker(pr: int) -> str:
    return f"<!-- factory:findings pr={int(pr)} -->"


def review_for_head(comments: Sequence[dict], head: str, bot_login: str) -> str | None:
    """The body of the newest Review comment by the App whose gate line names this head."""
    slug = bot_login[:-5] if bot_login.lower().endswith("[bot]") else bot_login
    found: str | None = None
    for comment in comments or ():
        login = (comment.get("user") or {}).get("login") or ""
        if not is_factory_app(login, slug):
            continue
        body = comment.get("body") or ""
        gate = parse_gate(body)
        if gate and gate.source == "review" and gate.head == head:
            found = body
    return found


def standards_findings(body: str) -> list[Finding]:
    """The `repo_standard` and `baseline_smell` lines of the Review's Standards section, as
    (kind, description, path, fix). A line that does not parse is dropped."""
    out: list[Finding] = []
    in_standards = False
    for line in (body or "").splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            in_standards = heading.group("name") == "Standards"
            continue
        match = _LINE_RE.match(line) if in_standards else None
        if match and match.group("kind") in STANDARDS_KINDS:
            out.append(
                (
                    match.group("kind"),
                    match.group("desc"),
                    match.group("path") or "",
                    match.group("fix"),
                )
            )
    return out


def section(pr: int, title: str, findings: Sequence[Finding]) -> str:
    """One issue comment: the marker, the pull request, then one line per Finding."""
    lines = [
        marker(pr),
        f"### Pull request #{int(pr)}: {neutralize(title).strip()}",
        "",
    ]
    for kind, description, path, fix in findings:
        where = f" (`{neutralize(path)}`)" if path else ""
        lines.append(
            f"- **{neutralize(kind)}** {neutralize(description)}{where}. "
            f"Fix: {neutralize(fix)}"
        )
    return "\n".join(lines) + "\n"


def collect(gh: Any, repo: str, pr: int, head: str, app_slug: str) -> str:
    """Append the pull request's Standards Findings once. Returns what was done."""
    review = review_for_head(gh.pr_comments(repo, pr), head, f"{app_slug}[bot]")
    findings = standards_findings(review or "")
    if not findings:
        return "no Standards Findings"
    title = gh.pr(repo, pr).get("title") or ""
    text = section(pr, title, findings)
    with TemporaryDirectory() as tmp:
        issues = gh.open_issues_labelled(repo, LABEL)
        if issues:
            issue = min(issues)
            seen = marker(pr)
            if any(
                (c.get("body") or "").startswith(seen)
                for c in gh.pr_comments(repo, issue)
            ):
                return f"already collected on #{issue}"
        else:
            issue = gh.create_issue(
                repo,
                ISSUE_TITLE,
                write_comment(Path(tmp), "issue.md", ISSUE_BODY),
                (LABEL,),
            )
        gh.comment(repo, issue, write_comment(Path(tmp), "findings.md", text))
    return f"added {len(findings)} Finding(s) to #{issue}"


def main(argv: list[str] | None = None, gh: Any | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--head", required=True, help="the head commit that merged")
    parser.add_argument(
        "--app-slug",
        dest="app_slug",
        default="",
        help="the factory App's slug; default OWNER-factory",
    )
    args = parser.parse_args(argv)
    try:
        print(
            collect(
                gh or GitHub(),
                args.repo,
                args.pr,
                args.head,
                args.app_slug or default_app_slug(args.repo),
            )
        )
    except GitHubError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
