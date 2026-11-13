"""Fold a finished CI run on a factory draft into the existing rework path.

.github/workflows/ci-gate.yml runs this when CI completes. It does not build
anything. A failure posts a review-marker comment (the failing job name and a
short, redacted log excerpt) and moves the same labels Review moves, so
rework.yml starts. A green run, once Review has passed that head, takes
`in-progress` off the Ticket. Rework's wait step uses `wait` so revise sees a
CI failure that lands in the same round.

  collect  (GITHUB_TOKEN, actions: read) writes the failed jobs and excerpts.
  apply    (App token) re-reads the PR and posts, labels, or clears in-progress.
  wait     (GITHUB_TOKEN) blocks revise until CI has finished and, when CI
           failed, until this gate's comment is on the PR.

Usage:
  uv run python -m factory.ci_gate collect --repo O/R --run-id N --run-url URL \\
      --conclusion failure --event pull_request --head-branch factory/issue-N \\
      --head-sha SHA --head-repo O/R --out run-out
  uv run python -m factory.ci_gate apply --out run-out --app-slug S
  uv run python -m factory.ci_gate wait --repo O/R --pr N --sha SHA
"""

import argparse
import json
import os
import re
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from factory import claude
from factory.github import GitHub, GitHubError, author, label_names, write_comment
from factory.review_pr import (
    HUMAN_LABEL, MARKER, MAX_REWORK, REWORK_LABEL, Moves, charge_won,
    drop_in_progress, gate_line, head_charged, label_moves, linked_ticket, mark_for_run,
    move_labels, parse_gate, review_passed, rework_round,
)

CI_WORKFLOW = "ci.yml"
REVIEW_WORKFLOW = "review.yml"
FACTORY_BRANCH = re.compile(r"^factory/issue-([0-9]+)$")
EXCERPT_MAX_LINES = 60
EXCERPT_MAX_CHARS = 3000
NO_FAILED_JOB = "The CI run failed and no failed job was listed."
# CI conclusions that mean the run is over. `timed_out` and `skipped` are
# over too: Rework must not sit out the whole wait for a comment that will
# not be posted.
_CI_DONE = ("success", "failure", "cancelled", "timed_out", "skipped")
# Token shapes the factory or a test might print. CI itself holds no secrets;
# this is the belt on top of replacing values from the environment.
_TOKEN_RE = re.compile(
    r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{8,}"
    r"|github_pat_[A-Za-z0-9_]{8,}"
    r"|x-access-token:[^\s@]+"
    r"|sk-(?:ant|or)-[A-Za-z0-9_\-]{8,}")
_SECRET_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN",
               "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "FACTORY_SUBSCRIPTION_TOKEN",
               "FACTORY_OPENROUTER_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY")


@dataclass(frozen=True)
class FailedJob:
    name: str
    excerpt: str


@dataclass(frozen=True)
class GateEvent:
    """One CI completion plus the PR it belongs to. Tests build this directly."""
    conclusion: str
    event: str
    head_branch: str
    head_sha: str
    head_repo: str
    repo: str
    run_id: int
    run_url: str
    pr: Optional[int] = None
    pr_state: str = ""
    pr_draft: bool = False
    pr_author: str = ""
    pr_head_repo: str = ""
    pr_head_sha: str = ""
    labels: Tuple[str, ...] = ()
    body: str = ""
    comments: Tuple[dict, ...] = ()
    failed_jobs: Tuple[FailedJob, ...] = ()
    app_slug: str = ""
    issue_labels: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    action: str  # ignore | rework | human | join | settle | finish
    reason: str
    comment: str = ""
    add: Tuple[str, ...] = ()
    remove: Tuple[str, ...] = ()
    clear_in_progress: bool = False
    issue: Optional[int] = None
    nonce: Optional[str] = None


def env_secrets(env: dict) -> List[str]:
    return [env[name] for name in _SECRET_ENV if len(env.get(name) or "") >= 8]


def redact(text: str, hidden: Sequence[str]) -> str:
    for secret in hidden:
        if len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    return _TOKEN_RE.sub("[REDACTED]", text)


def bound_excerpt(log: str, hidden: Sequence[str] = ()) -> str:
    """The tail of a job log, secret values removed, capped so a comment can hold it."""
    text = redact(log or "", hidden).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines()
    truncated = False
    if len(lines) > EXCERPT_MAX_LINES:
        lines = lines[-EXCERPT_MAX_LINES:]
        truncated = True
    text = "\n".join(lines)
    if len(text) > EXCERPT_MAX_CHARS:
        text = text[-EXCERPT_MAX_CHARS:]
        truncated = True
    if truncated:
        text = "[...truncated]\n" + text
    return text.strip()


def failed_findings(jobs: Sequence[dict], logs: dict,
                    hidden: Sequence[str] = ()) -> Tuple[FailedJob, ...]:
    """One finding per job whose conclusion is failure. A missing log is still named."""
    found = []
    for job in jobs:
        if job.get("conclusion") != "failure":
            continue
        log = logs.get(job.get("id"))
        excerpt = bound_excerpt(log, hidden) if log else "(log unavailable)"
        found.append(FailedJob(str(job.get("name") or "CI"), excerpt))
    return tuple(found)


def _fence(text: str) -> str:
    return (text or "").replace("```", "'''")


def _ignore_reason(event: GateEvent) -> Optional[str]:
    # CI completes on pull_request. Review completes on pull_request_target.
    # Both are same-repo pull-request events; the workflow `if` admits both.
    if event.event not in ("pull_request", "pull_request_target"):
        return f"CI event is {event.event or 'unset'}, not a pull request"
    if event.head_repo != event.repo:
        return "CI ran for a fork"
    if event.pr is None:
        return "no open pull request for this head"
    if event.pr_state != "OPEN":
        return f"pull request is {event.pr_state or 'missing'}"
    if event.pr_head_repo != event.repo:
        return "pull request head is a fork"
    match = FACTORY_BRANCH.fullmatch(event.head_branch or "")
    if not match:
        return "not a factory/issue-<N> branch"
    if event.pr_head_sha != event.head_sha:
        return "CI head is not the pull request's current head"
    if event.pr_author != f"{event.app_slug}[bot]":
        return "pull request was not opened by the factory App"
    linked = linked_ticket(event.body, event.repo)
    if linked is None:
        return "pull request closes no Ticket"
    if linked != int(match.group(1)):
        return "branch and the Ticket it closes disagree"
    return None


def _render_failure(event: GateEvent, moves: Moves, charged: bool, nonce: Optional[str],
                    joining: bool) -> str:
    labels = list(event.labels)
    labels_after = [label for label in labels if label not in moves.remove] + list(moves.add)
    issue = linked_ticket(event.body, event.repo)
    jobs = event.failed_jobs or (FailedJob("CI", NO_FAILED_JOB),)
    gate = gate_line(event.head_sha, charged, "ci", ci_run=event.run_id,
                     nonce=nonce if charged else None, add=moves.add if charged else ())
    lines = [MARKER, gate, "## Factory review: BLOCKED", ""]
    against = f"Ticket #{issue}" if issue else "the pull request"
    lines.append(f"Reviewed `{event.head_sha[:12]}` against {against}.")
    if joining:
        lines.append(f"CI failed on `{event.head_sha[:12]}`. This head is already in a "
                     f"rework round, so the counter stays.")
    elif moves.outcome == "rework":
        lines.append(f"Sent to rework: round {rework_round(labels_after)} of {MAX_REWORK}.")
    elif moves.outcome == "human":
        lines.append(f"CI blocked this PR again after {MAX_REWORK} rework rounds, "
                     f"so it is labelled `{HUMAN_LABEL}` and the factory stops here.")
    lines += ["", "### Spec: BLOCKER", "",
              "Required CI failed. This is a blocker the rework round must fix."]
    for job in jobs:
        lines += ["",
                  f"- **ci_failure** Job `{job.name}` failed ([run]({event.run_url})). "
                  "Fix: make the Project check pass. Log excerpt:",
                  "", "```", _fence(_TOKEN_RE.sub("[REDACTED]", job.excerpt)) or "(no log)", "```"]
    lines += ["", "A failing required CI run sends this PR to rework, on the same "
              "counter as a Spec blocker. The merge is a human's."]
    return "\n".join(lines) + "\n"


def conclusion_for_trigger(workflow: str, conclusion: str, ci_run: Optional[dict]) -> str:
    """The CI conclusion this gate should judge.

    A Review completion is not a CI result. When Review finishes, only an
    already-green CI run for the same head is a success; anything else is
    ignored so this path never starts a rework round. CI's own completion
    still carries its own conclusion.
    """
    if workflow != "Review":
        return conclusion
    if (ci_run or {}).get("conclusion") == "success":
        return "success"
    return "ignored"


def decide(event: GateEvent, nonce: str = "") -> Decision:
    """What to do with one CI completion. Pure: the caller performs the writes."""
    if event.conclusion not in ("success", "failure"):
        return Decision("ignore", f"CI conclusion is {event.conclusion or 'unset'}")
    reason = _ignore_reason(event)
    if reason:
        return Decision("ignore", reason)
    if event.conclusion == "success":
        return _decide_success(event)
    return _decide_failure(event, nonce)


def _decide_success(event: GateEvent) -> Decision:
    if not review_passed(event.comments, event.head_sha):
        return Decision("ignore", "review has not passed this head")
    # A green re-run of a head that already entered rework must not drop the
    # one-at-a-time lock while that round is still open.
    if head_charged(event.comments, event.head_sha) and REWORK_LABEL in event.labels:
        return Decision("ignore", "a rework round for this head is still open")
    issue = linked_ticket(event.body, event.repo)
    if "in-progress" not in event.issue_labels:
        return Decision("ignore", "in-progress is already off")
    return Decision("settle", "review passed and CI is green",
                    clear_in_progress=True, issue=issue)


def _decide_failure(event: GateEvent, nonce: str) -> Decision:
    if not event.pr_draft:
        return Decision("ignore", "pull request is not a draft")
    if HUMAN_LABEL in event.labels:
        return Decision("ignore", "pull request is ready-for-human")
    posted = mark_for_run(event.comments, event.run_id)
    if posted is not None:
        return _duplicate(event, posted)
    if head_charged(event.comments, event.head_sha):
        return Decision("join", "this head is already in a rework round", comment=_join_comment(event))
    moves = label_moves(list(event.labels), True)
    comment = _render_failure(event, moves, charged=True, nonce=nonce, joining=False)
    return Decision(moves.outcome, "required CI failed", comment=comment,
                    add=moves.add, remove=moves.remove, nonce=nonce)


def _duplicate(event: GateEvent, meta) -> Decision:
    """The same CI run was already posted. Finish labels only if that write stopped halfway."""
    if not meta.charged:
        return Decision("ignore", "duplicate ci run")
    labels = list(event.labels)
    missing = tuple(label for label in meta.add if label not in labels)
    remove = ()
    if HUMAN_LABEL in meta.add and REWORK_LABEL in labels:
        remove = (REWORK_LABEL,)
    if not missing and not remove:
        return Decision("ignore", "duplicate ci run")
    return Decision("finish", "duplicate ci run, labels were not applied",
                    add=missing, remove=remove)


def _review_ready(review_run: Optional[dict], comments: Sequence, head_sha: str) -> bool:
    for comment in comments:
        meta = parse_gate(comment.get("body") or "")
        if meta and meta.head == head_sha and meta.source == "review":
            return True
    review_conclusion = (review_run or {}).get("conclusion") or ""
    return review_conclusion in ("success", "failure", "cancelled", "skipped")


def _failure_comment_posted(ci_run: Optional[dict], comments: Sequence) -> bool:
    run_id = (ci_run or {}).get("databaseId")
    return any(f"ci-run={run_id}" in (comment.get("body") or "") for comment in comments)


def inputs_ready(ci_run: Optional[dict], review_run: Optional[dict], comments: Sequence,
                 head_sha: str) -> bool:
    """True when revise can read this head's CI result and its review.

    A failure is ready only once the gate's comment names that run, so the
    agent is not started on the review alone. `timed_out`, `cancelled` and
    `skipped` are finished runs and do not wait for that comment. A review
    comment for the head is enough; if the review workflow has already
    finished without one, stop waiting.
    """
    conclusion = (ci_run or {}).get("conclusion") or ""
    if conclusion not in _CI_DONE:
        return False
    if conclusion == "failure" and not _failure_comment_posted(ci_run, comments):
        return False
    return _review_ready(review_run, comments, head_sha)


def wait_for_inputs(fetch: Callable, sleep: Callable, monotonic: Callable, timeout: float,
                    interval: float, head_sha: str, failure_grace: float = 120) -> str:
    """Poll until inputs_ready or the timeout. Returns 'ready' or 'timeout'.

    `fetch` returns `(ci_run, review_run, comments)` and may raise GitHubError.
    A read error starts another poll. It does not fail the rework. Once CI has
    failed and Review is ready, wait only `failure_grace` seconds for the
    gate's comment. The same grace applies when no CI run exists for the head
    and Review is already ready. The gate posts nothing for a non-draft, a
    fork, or `ready-for-human`.
    """
    start = monotonic()
    failure_since = None
    missing_since = None
    while True:
        try:
            ci_run, review_run, comments = fetch()
        except GitHubError:
            print("::warning title=CI gate wait::GitHub could not be read; polling again")
            ci_run, review_run, comments = None, None, []
        else:
            if inputs_ready(ci_run, review_run, comments, head_sha):
                return "ready"
        conclusion = (ci_run or {}).get("conclusion") or ""
        review_ready = _review_ready(review_run, comments, head_sha)
        if (conclusion == "failure" and not _failure_comment_posted(ci_run, comments)
                and review_ready):
            if failure_since is None:
                failure_since = monotonic()
            if monotonic() - failure_since >= failure_grace:
                return "ready"
        else:
            failure_since = None
        if ci_run is None and review_ready:
            if missing_since is None:
                missing_since = monotonic()
            if monotonic() - missing_since >= failure_grace:
                return "ready"
        else:
            missing_since = None
        if monotonic() - start >= timeout or interval <= 0:
            return "timeout"
        sleep(interval)


def collect(args, gh: Optional[GitHub] = None) -> int:
    gh = gh or GitHub()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    hidden = env_secrets(os.environ)
    conclusion, run_id, run_url = args.conclusion, args.run_id, args.run_url
    if getattr(args, "workflow", "CI") == "Review":
        try:
            ci_run = gh.workflow_run(args.repo, args.head_sha, CI_WORKFLOW)
        except GitHubError:
            ci_run = None
        conclusion = conclusion_for_trigger("Review", args.conclusion, ci_run)
        if conclusion == "success" and ci_run:
            run_id = int(ci_run["databaseId"])
            run_url = ci_run.get("url") or run_url
    jobs: Tuple[FailedJob, ...] = ()
    if conclusion == "failure":
        logs = {}
        raw_jobs = gh.jobs(args.repo, args.run_id)
        for job in raw_jobs:
            if job.get("conclusion") != "failure":
                continue
            try:
                logs[job.get("id")] = gh.job_log(args.repo, job["id"])
            except GitHubError:
                logs[job.get("id")] = ""
        jobs = failed_findings(raw_jobs, logs, hidden)
        if not jobs:
            jobs = (FailedJob("CI", NO_FAILED_JOB),)
    payload = {"conclusion": conclusion, "event": args.event, "head_branch": args.head_branch,
               "head_sha": args.head_sha, "head_repo": args.head_repo, "repo": args.repo,
               "run_id": run_id, "run_url": run_url,
               "failed_jobs": [{"name": job.name, "excerpt": job.excerpt} for job in jobs]}
    (out / "event.json").write_text(json.dumps(payload, indent=2) + "\n")
    names = ", ".join(job.name for job in jobs) or "none"
    print(f"CI run {run_id} {conclusion}: failed jobs: {names}")
    return 0


def _load_facts(path: Path) -> dict:
    raw = json.loads(path.read_text())
    raw["failed_jobs"] = tuple(FailedJob(job["name"], job["excerpt"]) for job in raw.get("failed_jobs") or [])
    raw["run_id"] = int(raw["run_id"])
    return raw


def _live_event(facts: dict, gh: GitHub, app_slug: str) -> GateEvent:
    prs = [pr for pr in gh.open_prs_for_branch(facts["repo"], facts["head_branch"])
           if pr.get("headRefOid") == facts["head_sha"]]
    if not prs:
        return GateEvent(app_slug=app_slug, **{k: facts[k] for k in (
            "conclusion", "event", "head_branch", "head_sha", "head_repo", "repo",
            "run_id", "run_url", "failed_jobs")})
    number = prs[0]["number"]
    pr = gh.pr(facts["repo"], number)
    comments = tuple(gh.pr_comments(facts["repo"], number))
    head_repo = gh.pull_head_repo(facts["repo"], number)
    issue = linked_ticket(pr.get("body") or "", facts["repo"])
    issue_labels: Tuple[str, ...] = ()
    if issue is not None:
        issue_labels = tuple(label_names(gh.issue(facts["repo"], issue)))
    return GateEvent(
        conclusion=facts["conclusion"], event=facts["event"], head_branch=facts["head_branch"],
        head_sha=facts["head_sha"], head_repo=facts["head_repo"], repo=facts["repo"],
        run_id=facts["run_id"], run_url=facts["run_url"], failed_jobs=facts["failed_jobs"],
        pr=number, pr_state=pr.get("state") or "", pr_draft=bool(pr.get("isDraft")),
        pr_author=author(pr), pr_head_repo=head_repo, pr_head_sha=pr.get("headRefOid") or "",
        labels=tuple(label_names(pr)), body=pr.get("body") or "", comments=comments,
        app_slug=app_slug, issue_labels=issue_labels)


def _join_comment(event: GateEvent) -> str:
    return _render_failure(event, Moves("pass"), charged=False, nonce=None, joining=True)


def apply(args, gh: Optional[GitHub] = None) -> int:
    gh = gh or GitHub()
    out = Path(args.out)
    facts = _load_facts(out / "event.json")
    event = _live_event(facts, gh, args.app_slug)
    if event.pr is None:
        print("CI gate ignored: no open pull request for this head")
        return 0
    nonce = secrets.token_hex(8)
    decision = decide(event, nonce=nonce)
    if decision.action == "ignore":
        print(f"CI gate ignored: {decision.reason}")
        return 0
    comment_id = None
    if decision.comment:
        path = write_comment(out, "comment.md", decision.comment)
        if claude.scrub(out, env_secrets(os.environ)):
            print("::warning title=Secret scrubbed::The CI gate's files held a secret value; "
                  "it was redacted")
        comment_id = gh.comment(event.repo, event.pr, path)
    if decision.nonce and not charge_won(gh.pr_comments(event.repo, event.pr), event.head_sha,
                                         decision.nonce):
        # Posted as the charge before the other comment was visible. Rewrite it
        # so it does not claim a round it did not take.
        joined = write_comment(out, "comment.md", _join_comment(event))
        gh.update_comment(event.repo, comment_id, joined)
        print("CI gate joined a round already charged; labels unchanged")
        return 0
    move_labels(gh, event.repo, event.pr, decision.add, decision.remove)
    if decision.clear_in_progress and decision.issue:
        drop_in_progress(gh, event.repo, decision.issue)
    print(f"CI gate {decision.action}: {decision.reason}")
    return 0


def wait(args, gh: Optional[GitHub] = None, sleep=time.sleep, monotonic=time.monotonic) -> int:
    gh = gh or GitHub()

    def fetch():
        return (gh.workflow_run(args.repo, args.sha, CI_WORKFLOW),
                gh.workflow_run(args.repo, args.sha, REVIEW_WORKFLOW),
                gh.pr_comments(args.repo, args.pr))

    status = wait_for_inputs(fetch, sleep, monotonic, args.timeout, args.interval, args.sha,
                             args.failure_grace)
    if status == "timeout":
        print("::warning title=CI gate wait ended::CI or Review did not finish before the "
              "wait; rework continues with the comments posted so far")
    else:
        print(f"Rework inputs for {args.sha[:12]} are ready")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="step", required=True)

    c = sub.add_parser("collect")
    c.add_argument("--repo", required=True)
    c.add_argument("--run-id", type=int, required=True)
    c.add_argument("--run-url", required=True)
    c.add_argument("--conclusion", required=True)
    c.add_argument("--workflow", default="CI")
    c.add_argument("--event", required=True)
    c.add_argument("--head-branch", required=True)
    c.add_argument("--head-sha", required=True)
    c.add_argument("--head-repo", required=True)
    c.add_argument("--out", required=True)

    a = sub.add_parser("apply")
    a.add_argument("--out", required=True)
    a.add_argument("--app-slug", required=True)

    w = sub.add_parser("wait")
    w.add_argument("--repo", required=True)
    w.add_argument("--pr", type=int, required=True)
    w.add_argument("--sha", required=True)
    w.add_argument("--timeout", type=float, default=900)
    w.add_argument("--interval", type=float, default=15)
    w.add_argument("--failure-grace", type=float, default=120)

    args = parser.parse_args(argv)
    try:
        return {"collect": collect, "apply": apply, "wait": wait}[args.step](args)
    except (RuntimeError, GitHubError, OSError, ValueError, KeyError) as e:
        print(f"::error title=CI gate {args.step} failed::{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
