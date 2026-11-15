"""The last step of a Factory run: leave a Run record (docs/factory/README.md, "Run records").

A Run record is one small JSON object, `schema: 1`, with facts and numbers and no
model text. This step writes it to <out>/run.json and appends it, as a hidden
`<!-- factory:run {...} -->` marker, to the comment the run already posted
(docs/adr/0010-run-records-live-in-comment-markers.md).

  write   (App token) runs after the agent step started, whatever happened. Only
          `implement.yml` calls it today; the other workflows will pass their own
          `--workflow`.

The step holds the App token and the agent could write anything into --out, so it
trusts nothing there. It takes the run's identity from its own arguments (the
workflow's context). From <out>/result.json it copies only known number fields and
checks each one's type. A field that fails its check is written as null with a
workflow warning, and the marker is still posted. The comment it edits is found
among the bot's own comments on the Ticket, never from a file in --out.
"""
import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from factory import claude
from factory.github import GitHub, GitHubError, write_comment
from factory.switch_rule import LOGINS
from factory.ticket import OPENED_PREFIX, UNCHANGED_FILE, failed_prefix

SCHEMA = 1
WORKFLOWS = ("implement", "rework", "review")
REASONS = ("no-result", "no-change", "check-failed", "publish-failed", "unparsed-findings",
           "cancelled")
VERDICTS = ("PASS", "BLOCKED")
GATES = ("pass", "rework", "human", "human-owned", "stale", "same-round", "ci-blocked", "closed")
COST_NOTE = "client-estimate"
MARKER_RE = re.compile(r"<!-- factory:run ")
_SUBTYPE_RE = re.compile(r"^error_[a-z_]+$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_VERSION_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,99}$")
# Anything that looks like a credential, or that could close the HTML comment.
_UNSAFE_RE = re.compile(r"-->|<!--|sk-[A-Za-z0-9_-]{6,}|gh[pousr]_[A-Za-z0-9]{10,}"
                        r"|github_pat_|xox[abposr]-|eyJ[A-Za-z0-9_-]{10,}")
_MAX_FILE = 200_000


class _Warn:
    """Collects the fields that failed their check; never prints the value."""

    def __init__(self):
        self.names: List[str] = []

    def bad(self, name: str) -> None:
        self.names.append(name)
        print(f"::warning title=Run record::the field {name} failed its check and is empty")


def _int(value, low=0) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        return None
    return value


def _num(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _text(value, pattern) -> Optional[str]:
    if not isinstance(value, str) or not pattern.match(value) or _UNSAFE_RE.search(value):
        return None
    return value


def _digits(value) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return _int(value, 1)
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,15}", value):
        return _int(int(value), 1)
    return None


def _choice(value, allowed) -> Optional[str]:
    return value if isinstance(value, str) and value in allowed else None


def _budget(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def read_numbers(out: Path) -> dict:
    """The saved numbers, or {} when the file is missing or unreadable."""
    path = Path(out) / "result.json"
    try:
        if not path.is_file() or path.stat().st_size > _MAX_FILE:
            return {}
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _tokens(numbers: dict) -> dict:
    """The four counts from `usage`, or summed from `modelUsage` when `usage` is all
    zero (the CLI does this when it stops at its budget cap)."""
    usage = numbers.get("usage") if isinstance(numbers.get("usage"), dict) else {}
    counts = {k: _int(usage.get(k)) for k in claude._TOKEN_KEYS}
    if all(not v for v in counts.values()):
        models = numbers.get("model_usage")
        if isinstance(models, dict):
            summed = {k: 0 for k in claude._TOKEN_KEYS}
            seen = False
            for per_model in models.values():
                if not isinstance(per_model, dict):
                    continue
                for key, model_key in zip(claude._TOKEN_KEYS, claude._MODEL_TOKEN_KEYS):
                    value = _int(per_model.get(model_key))
                    if value:
                        summed[key] += value
                        seen = True
            if seen:
                counts = summed
    return counts


def build_record(workflow: str, ctx: dict, numbers: dict, outcome: str, reason: Optional[str],
                 pr=None, head_sha=None, round_=0, verdict=None, gate=None,
                 now: Optional[datetime] = None) -> dict:
    """The Run record from trusted `ctx` and untrusted `numbers`. Bad fields become None."""
    warn = _Warn()

    def keep(name, value):
        if value is None:
            warn.bad(name)
        return value

    now = now or datetime.now(timezone.utc)
    tokens = _tokens(numbers)
    models = numbers.get("model_usage") if isinstance(numbers.get("model_usage"), dict) else {}
    model_ids = [m for m in models if _text(m, _MODEL_ID_RE)][:10]
    if len(model_ids) != len(models):
        warn.bad("model_ids")
    numbers_present = bool(numbers)
    cost = _num(numbers.get("total_cost_usd"))
    turns = _int(numbers.get("num_turns"))
    duration = _int(numbers.get("duration_ms"))
    if numbers_present:
        cost, turns, duration = (keep("cost_usd", cost), keep("turns", turns),
                                 keep("duration_ms", duration))
        tokens = {k: keep(k, v) for k, v in tokens.items()}
    record = {
        "schema": SCHEMA,
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "workflow": keep("workflow", _choice(workflow, WORKFLOWS)),
        "run_id": keep("run_id", _digits(ctx.get("run_id"))),
        "attempt": keep("attempt", _digits(ctx.get("attempt"))),
        "repo": keep("repo", _text(ctx.get("repo"), _REPO_RE)),
        "issue": _digits(ctx.get("issue")) if ctx.get("issue") is not None else None,
        "pr": _digits(pr) if pr is not None else None,
        "project": (keep("project", _text(ctx.get("project"), _PROJECT_RE))
                    if ctx.get("project") else None),
        "login": keep("login", _choice(ctx.get("login"), LOGINS)),
        "model": keep("model", _choice(ctx.get("model"), claude.MODELS)),
        "budget": keep("budget", _budget(ctx.get("budget"))),
        "model_ids": model_ids,
        "claude_code_version": keep("claude_code_version",
                                    _text(ctx.get("claude_code_version"), _VERSION_RE)),
        "round": keep("round", _int(round_)),
        "outcome": keep("outcome", _choice(outcome, ("ok", "fail"))),
        "reason": None,
        "verdict": keep("verdict", _choice(verdict, VERDICTS)) if verdict is not None else None,
        "gate": keep("gate", _choice(gate, GATES)) if gate is not None else None,
        "cost_usd": cost,
        "cost_note": COST_NOTE,
        "turns": turns,
        "duration_ms": duration,
        **tokens,
        "head_sha": (keep("head_sha", _text(head_sha, _SHA_RE))
                     if head_sha is not None else None),
    }
    if reason is not None:
        if reason in REASONS or (isinstance(reason, str) and _SUBTYPE_RE.match(reason)
                                 and not _UNSAFE_RE.search(reason)):
            record["reason"] = reason
        else:
            warn.bad("reason")
    return record


def marker(record: dict) -> str:
    return "<!-- factory:run " + json.dumps(record, separators=(",", ":")) + " -->"


# ---- the Implement run -----------------------------------------------------------

_PR_URL = r"https://github\.com/{repo}/pull/([0-9]+)"


def _implement_reason(args, numbers: dict, out: Path) -> Optional[str]:
    """Why an Implement run that did not publish failed. Only values from the fixed lists."""
    outcomes = (args.job_status, args.build_outcome, args.verify_outcome, args.publish_outcome)
    if "cancelled" in outcomes:
        return "cancelled"
    if args.build_outcome != "success":
        subtype = numbers.get("subtype")
        if isinstance(subtype, str) and subtype != "success" and _SUBTYPE_RE.match(subtype):
            return subtype
        return "no-result"
    if args.verify_outcome == "failure":
        return "check-failed"
    return "no-change" if (out / UNCHANGED_FILE).is_file() else "publish-failed"


def _bot_comment(comments: List[dict], slug: str, prefix: str) -> Optional[dict]:
    """The newest comment by the factory bot that starts with `prefix` and holds no record."""
    bot = f"{slug}[bot]".lower()
    found = [c for c in comments
             if isinstance(c.get("body"), str) and c["body"].startswith(prefix)
             and not MARKER_RE.search(c["body"])
             and str((c.get("user") or {}).get("login", "")).lower() == bot]
    return max(found, key=lambda c: c["id"]) if found else None


def write(args, gh: Optional[GitHub] = None) -> int:
    """Build the record, write <out>/run.json and put the marker on the run's comment."""
    gh = gh or GitHub()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.workflow == "review":
        from factory.run_record_review import write_review
        return write_review(args, gh)
    if args.workflow != "implement":
        raise RuntimeError(f"no Run record is wired for the {args.workflow} workflow yet")
    numbers = read_numbers(out)
    ok = (args.publish_outcome == "success" and args.job_status != "cancelled")
    prefix = OPENED_PREFIX if ok else failed_prefix(args.run_url)
    pr = head_sha = None
    target = None
    try:
        target = _bot_comment(gh.pr_comments(args.repo, args.issue), args.app_slug, prefix)
    except GitHubError as e:
        print(f"::warning title=Run record::could not read the Ticket's comments: {e}")
    if ok and target:
        found = re.match(re.escape(OPENED_PREFIX) + _PR_URL.format(repo=re.escape(args.repo)),
                         target["body"])
        pr = int(found.group(1)) if found else None
        if pr:
            try:
                head_sha = gh.pr(args.repo, pr).get("headRefOid")
            except GitHubError as e:
                print(f"::warning title=Run record::could not read the pull request: {e}")
    ctx = {"repo": args.repo, "run_id": args.run_id, "attempt": args.attempt,
           "issue": args.issue, "project": args.project, "login": args.login,
           "model": args.model, "budget": args.budget,
           "claude_code_version": args.claude_code_version}
    reason = None if ok else _implement_reason(args, numbers, out)
    record = build_record("implement", ctx, numbers, "ok" if ok else "fail", reason,
                          pr=pr, head_sha=head_sha, round_=0)
    line = marker(record)
    (out / "run.json").write_text(json.dumps(record, indent=2) + "\n")
    try:
        if target:
            body = target["body"].rstrip("\n") + "\n" + line + "\n"
            gh.update_comment(args.repo, target["id"], write_comment(out, "run-comment.md", body))
        else:
            body = f"The factory run for this Ticket ended: [run]({args.run_url}).\n{line}\n"
            gh.comment(args.repo, args.issue, write_comment(out, "run-comment.md", body))
    except GitHubError as e:
        print(f"::warning title=Run record::could not post the record: {e}")
    print(f"Run record: {record['outcome']}" + (f" ({record['reason']})" if record["reason"] else ""))
    return 0


def _issue(text: str) -> Optional[int]:
    """`--issue`, or nothing when the run has no Ticket (a pull request that closes none)."""
    return None if text in ("", "null") else int(text)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="step", required=True)
    w = sub.add_parser("write")
    w.add_argument("--workflow", choices=WORKFLOWS, required=True)
    w.add_argument("--out", required=True)
    w.add_argument("--repo", required=True)
    w.add_argument("--run-id", dest="run_id", required=True)
    w.add_argument("--attempt", required=True)
    w.add_argument("--issue", type=_issue, default=None)
    w.add_argument("--pr", type=int, default=None)
    w.add_argument("--head-sha", dest="head_sha", default="")
    w.add_argument("--project", default="")
    w.add_argument("--login", required=True)
    w.add_argument("--model", required=True)
    w.add_argument("--budget", required=True)
    w.add_argument("--claude-code-version", dest="claude_code_version", required=True)
    w.add_argument("--app-slug", required=True)
    w.add_argument("--run-url", required=True)
    w.add_argument("--job-status", default="")
    w.add_argument("--build-outcome", default="")
    w.add_argument("--verify-outcome", default="")
    w.add_argument("--publish-outcome", default="")
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
