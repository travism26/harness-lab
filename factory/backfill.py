"""One-off: build a Run record for every past Factory run whose agent started.

  uv run python -m factory.backfill --repo OWNER/NAME [--out PATH] [--scratch DIR]

The Run record (docs/factory/README.md, "Run records") only exists for runs after it
shipped. This lists the Implement, Rework and Review runs through `gh`, downloads each
run's artifact into a scratch directory outside the repo, builds the record with
`factory.run_record.build_record`, and writes one JSONL file, ordered by run id then
attempt, so a second run gives the same bytes. Every record carries `backfilled: true`.

Old artifacts predate `result.json`, so the numbers come from the transcript's closing
result line, read through the same number-only path the factory uses; the transcript is
never copied and the download is deleted as soon as the record is built. What the run
did not leave (login, model alias, budget, Claude Code version) is null, not guessed.
A run with no artifact still gets a record, with null numbers. A run that started no
agent gets none. Old comments are not edited.
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import List, Optional

from factory import claude, review_pr
from factory import run_record as rr
from factory import run_record_review as rrr
from factory.github import GitHub, GitHubError
from factory.ticket import OPENED_PREFIX

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = Path(__file__).resolve().parent / "run-records-backfill.jsonl"
WORKFLOWS = ("implement", "rework", "review")
# The first words of each workflow's agent step.
_AGENT_STEP = {"implement": "Build (agent", "rework": "Rework (agent",
               "review": "Review (fresh context"}
_BRANCH_RE = re.compile(r"^factory/issue-([0-9]+)$")
_MAX_CONTEXT = 200_000


class BackfillGitHub(GitHub):
    """The extra `gh` calls the backfill makes. Tests pass a fake with the same methods."""

    def workflow_runs(self, repo: str, workflow: str) -> List[dict]:
        out = self._gh(["api", "--paginate", "--slurp",
                        f"repos/{repo}/actions/workflows/{workflow}.yml/runs?per_page=100"])
        return [r for page in json.loads(out) for r in page.get("workflow_runs", [])]

    def attempt_run(self, repo: str, run_id: int, attempt: int) -> dict:
        return json.loads(self._gh(["api", f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}"]))

    def attempt_jobs(self, repo: str, run_id: int, attempt: int) -> List[dict]:
        out = self._gh(["api", f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs"
                               "?per_page=100", "--jq", ".jobs"])
        return json.loads(out)

    def run_artifacts(self, repo: str, run_id: int) -> List[dict]:
        out = self._gh(["api", f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100",
                        "--jq", ".artifacts"])
        return json.loads(out)

    def download_artifact(self, repo: str, run_id: int, name: str, dest: Path) -> None:
        self._gh(["run", "download", str(run_id), "-R", repo, "-n", name, "-D", str(dest)])


def _agent_started(jobs: List[dict], workflow: str) -> bool:
    for job in jobs:
        for step in job.get("steps") or []:
            if (str(step.get("name", "")).startswith(_AGENT_STEP[workflow])
                    and step.get("conclusion") not in (None, "skipped")):
                return True
    return False


def _read_json(path: Path) -> dict:
    try:
        if path.stat().st_size > _MAX_CONTEXT:
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
        numbers = rr.read_numbers(path.parent)
        if numbers:
            break
    if not numbers:
        for path in sorted(dest.rglob("agent.jsonl")):
            message = claude.result_message(path.read_text(errors="replace"))
            if message:
                claude.save_numbers(dest, message)
                numbers = rr.read_numbers(dest)
                break
    contexts = sorted(dest.rglob("context.json"))
    return numbers, (_read_json(contexts[0]) if contexts else {})


def _artifact(gh, repo: str, run_id: int, attempt: int) -> Optional[str]:
    for art in gh.run_artifacts(repo, run_id):
        name = art.get("name")
        if isinstance(name, str) and name.endswith(f"-{attempt}") and not art.get("expired"):
            return name
    return None


def _name_number(name: Optional[str], key: str) -> Optional[int]:
    found = re.search(rf"(?:^|-){key}([0-9]+)-", name or "")
    return int(found.group(1)) if found else None


def _rework_round(comments: List[dict], slug: str, created: str) -> Optional[int]:
    """The highest round the bot's charging comments had given when the run was created."""
    bot = f"{slug}[bot]".lower()
    rounds = []
    for c in comments:
        meta = review_pr.parse_gate(c.get("body") or "")
        if not meta or not meta.charged:
            continue
        if str((c.get("user") or {}).get("login", "")).lower() != bot:
            continue
        if c.get("created_at") and created and c["created_at"] > created:
            continue
        rounds += [int(x.split(":")[1]) for x in meta.add if re.fullmatch(r"rework:[0-9]+", x)]
    return max(rounds, default=None)


def _review_round(body: str) -> Optional[int]:
    meta = review_pr.parse_gate(body)
    if not meta or not meta.charged:
        return None
    if review_pr.HUMAN_LABEL in meta.add:
        return review_pr.MAX_REWORK
    rounds = [int(x.split(":")[1]) for x in meta.add if re.fullmatch(r"rework:[0-9]+", x)]
    return max(rounds, default=None)


def _safely(call, default):
    try:
        return call()
    except GitHubError as e:
        print(f"::warning title=Backfill::{e}", file=sys.stderr)
        return default


def _record(gh, args, workflow: str, run: dict, attempt: int, numbers: dict, context: dict,
            artifact: Optional[str]) -> dict:
    run_id = run["id"]
    stamp = datetime.strptime(run["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    conclusion = run.get("conclusion")
    ok = conclusion == "success"
    branch = _BRANCH_RE.match(run.get("head_branch") or "")
    pulls = run.get("pull_requests") or []
    pr = context.get("pr") or _name_number(artifact, "pr") or (pulls[0].get("number") if pulls else None)
    issue = (context.get("issue") or context.get("ticket") or _name_number(artifact, "issue")
             or (int(branch.group(1)) if branch and workflow != "implement" else None))
    head_sha = context.get("head_sha") if workflow == "review" else None
    verdict = gate = round_ = None
    comments = _safely(lambda: gh.pr_comments(args.repo, pr), []) if pr and workflow != "implement" else []
    if workflow == "implement":
        round_ = 0
        if ok and issue and not pr:
            opened = [c for c in _safely(lambda: gh.pr_comments(args.repo, issue), [])
                      if str((c.get("user") or {}).get("login", "")).lower() == f"{args.app_slug}[bot]".lower()
                      and (c.get("body") or "").startswith(OPENED_PREFIX)]
            found = re.match(re.escape(OPENED_PREFIX) + rr._PR_URL.format(repo=re.escape(args.repo)),
                             max(opened, key=lambda c: c["id"])["body"]) if opened else None
            pr = int(found.group(1)) if found else None
    elif workflow == "rework":
        round_ = _rework_round(comments, args.app_slug, run.get("created_at") or "")
    else:
        target = rrr._report(comments, args.app_slug, head_sha) if head_sha else None
        if target:
            verdict = review_pr.review_verdict(target["body"])
            gate = rrr._gate_of(target["body"])
            round_ = _review_round(target["body"])
    if workflow == "review" and pr and not issue:
        body = (_safely(lambda: gh.pr(args.repo, pr), {}) or {}).get("body") or ""
        issue = review_pr.linked_ticket(body, args.repo)
    reason = None
    if not ok:
        subtype = numbers.get("subtype")
        if conclusion == "cancelled":
            reason = "cancelled"
        elif isinstance(subtype, str) and subtype != "success" and rr._SUBTYPE_RE.match(subtype):
            reason = subtype
        elif artifact and not numbers:
            reason = "no-result"
    ctx = {"repo": args.repo, "run_id": run_id, "attempt": attempt, "issue": issue,
           "project": context.get("project")}
    with redirect_stdout(StringIO()):      # null identity fields would each warn
        record = rr.build_record(workflow, ctx, numbers, "ok" if ok else "fail", reason, pr=pr,
                                 head_sha=head_sha, round_=round_, verdict=verdict, gate=gate,
                                 now=stamp)
    record["backfilled"] = True
    return record


def collect(gh, args, scratch: Path):
    """(records, number of runs that started no agent)."""
    records, no_agent = [], 0
    for workflow in WORKFLOWS:
        for listed in gh.workflow_runs(args.repo, workflow):
            for attempt in range(1, int(listed.get("run_attempt") or 1) + 1):
                run = (listed if attempt == listed.get("run_attempt")
                       else gh.attempt_run(args.repo, listed["id"], attempt))
                if run.get("status") != "completed" or run.get("conclusion") == "skipped":
                    continue
                if not _agent_started(gh.attempt_jobs(args.repo, run["id"], attempt), workflow):
                    no_agent += 1
                    continue
                numbers, context, name = {}, {}, _artifact(gh, args.repo, run["id"], attempt)
                if name:
                    dest = scratch / f"{run['id']}-{attempt}"
                    dest.mkdir(parents=True, exist_ok=True)
                    try:
                        gh.download_artifact(args.repo, run["id"], name, dest)
                        numbers, context = _from_download(dest)
                    finally:
                        shutil.rmtree(dest, ignore_errors=True)
                records.append(_record(gh, args, workflow, run, attempt, numbers, context, name))
    records.sort(key=lambda r: (r["run_id"], r["attempt"]))
    return records, no_agent


def main(argv: Optional[List[str]] = None, gh=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--scratch", default=None,
                        help="where artifacts are downloaded; a fresh temp directory by default")
    parser.add_argument("--app-slug", dest="app_slug", default=None,
                        help="the factory App's slug; default OWNER-factory")
    args = parser.parse_args(argv)
    args.app_slug = args.app_slug or f"{args.repo.split('/')[0]}-factory"
    made = args.scratch is None
    scratch = Path(tempfile.mkdtemp(prefix="factory-backfill-")) if made else Path(args.scratch).resolve()
    if scratch == REPO_ROOT or REPO_ROOT in scratch.parents:
        print(f"error: the scratch directory {scratch} is inside the repo; "
              "a download holds transcripts", file=sys.stderr)
        return 2
    scratch.mkdir(parents=True, exist_ok=True)
    gh = gh or BackfillGitHub()
    try:
        records, no_agent = collect(gh, args, scratch)
    except GitHubError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        if made:
            shutil.rmtree(scratch, ignore_errors=True)
    lines = [json.dumps(r, separators=(",", ":")) for r in records]
    if any(rr._UNSAFE_RE.search(line) for line in lines):
        print("error: a record holds a token-shaped string; nothing was written", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(line + "\n" for line in lines))
    with_numbers = sum(1 for r in records if r["cost_usd"] is not None)
    print(f"Backfill: {len(records)} records ({with_numbers} with numbers, "
          f"{len(records) - with_numbers} without numbers); {no_agent} runs started no agent.")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
