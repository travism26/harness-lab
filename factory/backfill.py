"""One-off: build a Run record for every past Factory run whose agent started.

  uv run python -m factory.backfill --repo OWNER/NAME [--out PATH] [--scratch DIR]

The Run record (docs/factory/README.md, "Run records") only exists for runs after it
shipped. This lists the Implement, Rework and Review runs through `gh`, downloads each
run's artifact into a scratch directory outside the repo, builds the record with
`factory.record.build_record`, and writes one JSONL file, ordered by run id then
attempt, so a second run gives the same bytes. Every record carries `backfilled: true`.

Old artifacts predate `result.json`, so the numbers come from the transcript's closing
result line, read through the same number-only path the factory uses; the transcript is
never copied and the download is deleted as soon as the record is built. What the run
did not leave (login, model alias, budget, Claude Code version) is null, not guessed.
A run with no artifact still gets a record, with null numbers. A run that started no
agent gets none. Old comments are not edited.
"""

import argparse
import functools
import json
import re
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from factory import claude, review_pr
from factory.github import GitHub, GitHubError
from factory.record import (
    BACKFILL_FILE,
    MAX_FILE,
    UNSAFE_RE,
    WORKFLOWS,
    Outcomes,
    RunContext,
    bot_comments,
    build_record,
    failure_reason,
    opened_pr,
    read_numbers,
)
from factory.run_record_review import gate_of, reports
from factory.switch_rule import default_app_slug
from factory.ticket import OPENED_PREFIX, UNCHANGED, failed_prefix

REPO_ROOT = Path(__file__).resolve().parent.parent
# The first words of each workflow's agent step, and of the steps that explain a failure.
_AGENT_STEP = {
    "implement": "Build (agent",
    "rework": "Rework (agent",
    "review": "Review (fresh context",
}
_CHECK_STEP = "Run the new Project check"
_PUBLISH_STEP = {
    "implement": "Commit, push and open",
    "rework": "Commit and push the round",
    "review": "Post the report",
}
_BRANCH_RE = re.compile(r"^factory/issue-([0-9]+)$")
_ISSUE_URL_RE = re.compile(r"/issues/([0-9]+)$")


@dataclass
class RunAttempt:
    """What describes one attempt of one run: the listing, its jobs, and what its artifact held."""

    workflow: str
    run: dict
    attempt: int
    jobs: list[dict] = field(default_factory=list)
    numbers: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    artifact: str | None = None

    @property
    def run_url_tail(self) -> str:
        return f"/actions/runs/{self.run['id']}"

    @property
    def window(self) -> tuple:
        """(start, end) of the attempt, as GitHub's timestamps."""
        return (
            self.run.get("run_started_at") or self.run.get("created_at") or "",
            self.run.get("updated_at") or "",
        )


def _agent_started(jobs: list[dict], workflow: str) -> bool:
    return _step_conclusion(jobs, _AGENT_STEP[workflow]) not in ("", "skipped")


def _step_conclusion(jobs: list[dict], prefix: str) -> str:
    for job in jobs:
        for step in job.get("steps") or []:
            if str(step.get("name", "")).startswith(prefix):
                return step.get("conclusion") or ""
    return ""


def _read_json(path: Path) -> dict:
    try:
        if path.stat().st_size > MAX_FILE:
            return {}
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _from_download(dest: Path):
    """(numbers, context) from a downloaded artifact. Only the result line of the
    transcript is read; nothing else in it is kept."""
    numbers = {}
    for path in sorted(dest.rglob("result.json")):
        numbers = read_numbers(path.parent)
        if numbers:
            break
    if not numbers:
        for path in sorted(dest.rglob("agent.jsonl")):
            message = claude.result_message(path.read_text(errors="replace"))
            if message:
                claude.save_numbers(dest, message)
                numbers = read_numbers(dest)
                break
    contexts = sorted(dest.rglob("context.json"))
    return numbers, (_read_json(contexts[0]) if contexts else {})


def _artifact(gh, repo: str, run_id: int, attempt: int) -> str | None:
    for art in gh.run_artifacts(repo, run_id):
        name = art.get("name")
        if (
            isinstance(name, str)
            and name.endswith(f"-{attempt}")
            and not art.get("expired")
        ):
            return name
    return None


def _name_number(name: str | None, key: str) -> int | None:
    found = re.search(rf"(?:^|-){key}([0-9]+)-", name or "")
    return int(found.group(1)) if found else None


def _round_in_force(comments: list[dict], slug: str, created: str) -> int:
    """The highest round the bot's charging comments had given when the run was created; 0
    when it had charged none."""
    names: list[str] = []
    for c in bot_comments(comments, slug, unrecorded=False):
        meta = review_pr.parse_gate(c["body"])
        if not meta or not meta.charged:
            continue
        if c.get("created_at") and created and c["created_at"] > created:
            continue
        names += meta.add
    return review_pr.rework_round(names)


def _review_round(
    report: dict, comments: list[dict], slug: str, created: str
) -> int | None:
    """The round a Review ran in: the one its report charged, or when it charged nothing,
    the one in force when the run was created."""
    meta = review_pr.parse_gate(report["body"])
    if meta and meta.charged:
        if review_pr.is_stopped(meta.add):
            return review_pr.MAX_REWORK
        return review_pr.rework_round(list(meta.add)) or None
    return _round_in_force(comments, slug, created)


_LEGACY_HEAD_RE = re.compile(r"^Reviewed `([0-9a-f]{12})` against ", re.MULTILINE)
_LEGACY_ROUND_RE = re.compile(
    r"^Sent to rework: round ([0-9]+) of [0-9]+\.$", re.MULTILINE
)


def _with_gate_lines(comments: list[dict], slug: str) -> list[dict]:
    """The comments with a gate line put on each older bot report that has none. Before the
    gate line existed a report was its marker, its headline and `Reviewed <12 of the head>`;
    the gate line is rebuilt from that text so the live readers can read it. Only the bot's
    own comments are changed, and only in this copy."""
    mine = {id(c) for c in bot_comments(comments, slug, unrecorded=False)}
    changed = []
    for c in comments:
        body = c.get("body")
        if (
            id(c) in mine
            and isinstance(body, str)
            and body.startswith(review_pr.MARKER + "\n")
            and not review_pr.parse_gate(body)
        ):
            head = _LEGACY_HEAD_RE.search(body)
            if head:
                round_ = _LEGACY_ROUND_RE.search(body)
                human = (
                    any(f"`{label}`" in body for label in review_pr.STOPPED_LABELS)
                    and "rework rounds" in body
                )
                add = (
                    (review_pr.STOPPED_LABEL,)
                    if human
                    else (review_pr.REWORK_LABEL, f"factory:rework-{round_.group(1)}")
                    if round_
                    else ()
                )
                gate = review_pr.gate_line(head.group(1), bool(add), "review", add=add)
                first, rest = body.split("\n", 1)
                c = dict(c, body=f"{first}\n{gate}\n{rest}")
        changed.append(c)
    return changed


def _report_for_head(comments: list[dict], slug: str, head_sha: str) -> dict | None:
    """The bot's newest report for this head; an older report names only the first 12."""
    found = [
        c
        for c, meta in reports(comments, slug, unrecorded=False)
        if head_sha.startswith(meta.head)
    ]
    return max(found, key=lambda c: c["id"]) if found else None


def _report_in_window(comments: list[dict], slug: str, window: tuple) -> dict | None:
    """The bot's newest report comment created while the run was going."""
    start, end = window
    found = [
        (c, meta)
        for c, meta in reports(comments, slug, unrecorded=False)
        if start <= str(c.get("created_at") or "") <= end
    ]
    return max((c for c, _ in found), key=lambda c: c["id"]) if found else None


def _safely(call, default):
    try:
        return call()
    except GitHubError as e:
        print(f"::warning title=Backfill::{e}", file=sys.stderr)
        return default


def _issue_from_comments(
    repo_comments: list[dict], slug: str, attempt: RunAttempt
) -> int | None:
    """The Ticket the bot's comment that links this run's URL is on."""
    for c in bot_comments(repo_comments, slug, unrecorded=False):
        if f"{attempt.run_url_tail})" in c["body"]:
            found = _ISSUE_URL_RE.search(str(c.get("issue_url") or ""))
            if found:
                return int(found.group(1))
    return None


def _failed_unchanged(
    comments: list[dict], slug: str, attempt: RunAttempt, repo: str
) -> bool:
    """Whether the bot's failed comment for this run says nothing was changed."""
    prefix = failed_prefix(f"https://github.com/{repo}{attempt.run_url_tail}")
    start, end = attempt.window
    for c in bot_comments(comments, slug, unrecorded=False):
        made = str(c.get("created_at") or "")
        if (
            c["body"].startswith(prefix)
            and UNCHANGED in c["body"]
            and (not made or start <= made <= end)
        ):
            return True
    return False


def _record(gh, args, a: RunAttempt, repo_comments) -> dict:
    run = a.run
    stamp = datetime.strptime(run["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC
    )
    conclusion = run.get("conclusion")
    ok = conclusion == "success"
    branch = _BRANCH_RE.match(run.get("head_branch") or "")
    pulls = run.get("pull_requests") or []
    pr = (
        a.context.get("pr")
        or _name_number(a.artifact, "pr")
        or (pulls[0].get("number") if pulls else None)
    )
    issue = (
        a.context.get("issue")
        or a.context.get("ticket")
        or _name_number(a.artifact, "issue")
        or (int(branch.group(1)) if branch and a.workflow != "implement" else None)
    )
    head_sha = a.context.get("head_sha") if a.workflow == "review" else None
    verdict = gate = round_ = None
    comments = (
        _safely(lambda: gh.pr_comments(args.repo, pr), [])
        if pr and a.workflow != "implement"
        else []
    )
    ticket_comments = []
    if a.workflow == "implement":
        round_ = 0
        if not issue:
            issue = _issue_from_comments(repo_comments(), args.app_slug, a)
        if issue:
            ticket_comments = _safely(lambda: gh.pr_comments(args.repo, issue), [])
        if ok and issue and not pr:
            opened = [
                c
                for c in bot_comments(ticket_comments, args.app_slug, unrecorded=False)
                if c["body"].startswith(OPENED_PREFIX)
            ]
            pr = (
                opened_pr(
                    max(opened, key=lambda c: c["id"])["body"], args.repo, OPENED_PREFIX
                )
                if opened
                else None
            )
    elif a.workflow == "rework":
        round_ = (
            _round_in_force(comments, args.app_slug, run.get("created_at") or "")
            or None
        )
    else:
        comments = _with_gate_lines(comments, args.app_slug)
        report = (
            _report_for_head(comments, args.app_slug, head_sha)
            if head_sha
            else _report_in_window(comments, args.app_slug, a.window)
        )
        if report:
            mark = review_pr.parse_gate(report["body"])
            head_sha = head_sha or (mark.head if mark else None)
            verdict = review_pr.review_verdict(report["body"])
            if verdict not in ("PASS", "BLOCKED"):
                verdict = None
            gate = gate_of(report["body"])
            round_ = _review_round(
                report, comments, args.app_slug, run.get("created_at") or ""
            )
    if a.workflow == "review" and pr and not issue:
        body = (_safely(lambda: gh.pr(args.repo, pr), {}) or {}).get("body") or ""
        issue = review_pr.linked_ticket(body, args.repo)
    reason = None
    if not ok:
        outcomes = Outcomes(
            conclusion or "",
            _step_conclusion(a.jobs, _AGENT_STEP[a.workflow]),
            _step_conclusion(a.jobs, _CHECK_STEP),
            _step_conclusion(a.jobs, _PUBLISH_STEP[a.workflow]),
        )
        if outcomes.publish in ("success", "skipped"):  # neither fails at its publish
            outcomes = Outcomes(outcomes.job, outcomes.agent, outcomes.check, "")
        unchanged = (
            outcomes.publish == "failure"
            and bool(ticket_comments)
            and _failed_unchanged(ticket_comments, args.app_slug, a, args.repo)
        )
        reason = failure_reason(
            outcomes, a.numbers, unchanged, review=a.workflow == "review"
        )
        if (
            reason == "no-result" and not a.artifact
        ):  # the result line went with the artifact
            reason = None
    ctx = RunContext(
        repo=args.repo,
        run_id=run["id"],
        attempt=a.attempt,
        issue=issue,
        project=a.context.get("project"),
    )
    with redirect_stdout(StringIO()):  # null identity fields would each warn
        record = build_record(
            a.workflow,
            ctx,
            a.numbers,
            "ok" if ok else "fail",
            reason,
            pr=pr,
            head_sha=head_sha,
            round_=round_,
            verdict=verdict,
            gate=gate,
            now=stamp,
        )
    record["backfilled"] = True
    return record


def collect(gh, args, scratch: Path):
    """(records, number of runs that started no agent)."""
    records, no_agent = [], 0
    repo_comments = functools.lru_cache(maxsize=None)(
        lambda: _safely(lambda: gh.repo_comments(args.repo), [])
    )
    for workflow in WORKFLOWS:
        for listed in gh.workflow_runs(args.repo, workflow):
            for attempt in range(1, int(listed.get("run_attempt") or 1) + 1):
                run = (
                    listed
                    if attempt == listed.get("run_attempt")
                    else gh.attempt_run(args.repo, listed["id"], attempt)
                )
                if (
                    run.get("status") != "completed"
                    or run.get("conclusion") == "skipped"
                ):
                    continue
                jobs = gh.attempt_jobs(args.repo, run["id"], attempt)
                if not _agent_started(jobs, workflow):
                    no_agent += 1
                    continue
                made = RunAttempt(
                    workflow,
                    run,
                    attempt,
                    jobs,
                    artifact=_artifact(gh, args.repo, run["id"], attempt),
                )
                if made.artifact:
                    dest = scratch / f"{run['id']}-{attempt}"
                    dest.mkdir(parents=True, exist_ok=True)
                    try:
                        gh.download_artifact(args.repo, run["id"], made.artifact, dest)
                        made.numbers, made.context = _from_download(dest)
                    finally:
                        shutil.rmtree(dest, ignore_errors=True)
                records.append(_record(gh, args, made, repo_comments))
    records.sort(key=lambda r: (r["run_id"], r["attempt"]))
    return records, no_agent


def main(argv: list[str] | None = None, gh=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", default=str(BACKFILL_FILE))
    parser.add_argument(
        "--scratch",
        default=None,
        help="where artifacts are downloaded; a fresh temp directory by default",
    )
    parser.add_argument(
        "--app-slug",
        dest="app_slug",
        default=None,
        help="the factory App's slug; default OWNER-factory",
    )
    args = parser.parse_args(argv)
    args.app_slug = args.app_slug or default_app_slug(args.repo)
    made = args.scratch is None
    scratch = (
        Path(tempfile.mkdtemp(prefix="factory-backfill-"))
        if made
        else Path(args.scratch).resolve()
    )
    if scratch == REPO_ROOT or REPO_ROOT in scratch.parents:
        print(
            f"error: the scratch directory {scratch} is inside the repo; "
            "a download holds transcripts",
            file=sys.stderr,
        )
        return 2
    scratch.mkdir(parents=True, exist_ok=True)
    gh = gh or GitHub()
    try:
        records, no_agent = collect(gh, args, scratch)
    except GitHubError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        if made:
            shutil.rmtree(scratch, ignore_errors=True)
    lines = [json.dumps(r, separators=(",", ":")) for r in records]
    if any(UNSAFE_RE.search(line) for line in lines):
        print(
            "error: a record holds a token-shaped string; nothing was written",
            file=sys.stderr,
        )
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(line + "\n" for line in lines))
    with_numbers = sum(1 for r in records if r["cost_usd"] is not None)
    print(
        f"Backfill: {len(records)} records ({with_numbers} with numbers, "
        f"{len(records) - with_numbers} without numbers); {no_agent} runs started no agent."
    )
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
