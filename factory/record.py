"""The Run record itself: its fields and checks, its hidden marker, and what every writer shares.

A Run record (docs/factory/README.md, "Run records") is one small JSON object, `schema: 1`,
with facts and numbers and no model text. It lives in a hidden `<!-- factory:run {...} -->`
marker on the last line of one of the factory bot's comments
(docs/adr/0010-run-records-live-in-comment-markers.md).

`factory.run_record` (Implement and Rework), `factory.run_record_review` (Review) and
`factory.backfill` build records here. `factory.metrics` reads them back with `record_text`.
"""
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from factory import claude
from factory.github import GitHub, GitHubError, write_comment
from factory.switch_rule import LOGINS, is_factory_app

SCHEMA = 1
WORKFLOWS = ("implement", "rework", "review")
# Every workflow a record may name. `WORKFLOWS` stays the three `factory.backfill` rebuilds
# records for: the research path started after records did, so it has no past run to rebuild.
RECORDED = WORKFLOWS + ("research",)
REASONS = ("no-result", "no-change", "check-failed", "publish-failed", "unparsed-findings",
           "cancelled")
VERDICTS = ("PASS", "BLOCKED")
GATES = ("pass", "rework", "human", "human-owned", "stale", "same-round", "ci-blocked", "closed")
COST_NOTE = "client-estimate"
BACKFILL_FILE = Path(__file__).resolve().parent / "run-records-backfill.jsonl"
MAX_FILE = 200_000
MAX_REASON = 48
SUBTYPE_RE = re.compile(r"error_[a-z_]+")
PR_URL = r"https://github\.com/{repo}/pull/([0-9]+)"
MARKER_START = "<!-- factory:run "
MARKER_END = " -->"
_MARKER_LINE_RE = re.compile(re.escape(MARKER_START) + r"(\{[^\n]*\})" + re.escape(MARKER_END))
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_VERSION_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,99}$")
# Anything that looks like a credential.
TOKEN_RE = re.compile(r"sk-(?:ant|or)-|\bsk-[A-Za-z0-9_-]{6,}|gh[pousr]_[A-Za-z0-9]{10,}"
                      r"|github_pat_|xox[abposr]-|eyJ[A-Za-z0-9_-]{10,}")
# A credential, or anything that could open or close the HTML comment.
UNSAFE_RE = re.compile(r"-->|<!--|" + TOKEN_RE.pattern)


@dataclass(frozen=True)
class RunContext:
    """The run's identity. It comes from the workflow's context, never from a file in --out.
    Every field is checked again in `build_record`."""
    repo: Optional[str] = None
    run_id: object = None
    attempt: object = None
    issue: object = None
    project: Optional[str] = None
    login: Optional[str] = None
    model: Optional[str] = None
    budget: object = None
    claude_code_version: Optional[str] = None

    @classmethod
    def from_args(cls, args, issue: object = None) -> "RunContext":
        return cls(args.repo, args.run_id, args.attempt, issue, args.project, args.login,
                   args.model, args.budget, args.claude_code_version)


@dataclass(frozen=True)
class Outcomes:
    """How a run's steps ended. "" is a step that is not known to have run."""
    job: str = ""
    agent: str = ""
    check: str = ""
    publish: str = ""


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
    if not isinstance(value, str) or not pattern.match(value) or UNSAFE_RE.search(value):
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


def subtype_reason(value) -> Optional[str]:
    """A CLI error subtype (`error_max_budget_usd`) that may be a record's reason, or None."""
    if (isinstance(value, str) and len(value) <= MAX_REASON and SUBTYPE_RE.fullmatch(value)
            and not UNSAFE_RE.search(value)):
        return value
    return None


def read_numbers(out: Path) -> dict:
    """The saved numbers, or {} when the file is missing or unreadable."""
    path = Path(out) / "result.json"
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            return {}
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _tokens(numbers: dict) -> dict:
    """The four counts from `usage`. A count of the wrong type is None. When `usage` is
    well-typed and all zero, they are summed from `modelUsage` instead (the CLI reports zero
    there when it stops at its budget cap)."""
    usage = numbers.get("usage")
    counts = {k: _int(usage.get(k)) if isinstance(usage, dict) else None
              for k in claude.TOKEN_KEYS}
    well_typed = all(v is not None for v in counts.values())
    models = numbers.get("model_usage")
    if well_typed and not any(counts.values()) and isinstance(models, dict):
        summed = {k: 0 for k in claude.TOKEN_KEYS}
        seen = False
        for per_model in models.values():
            if not isinstance(per_model, dict):
                continue
            for key, model_key in zip(claude.TOKEN_KEYS, claude.MODEL_TOKEN_KEYS):
                value = _int(per_model.get(model_key))
                if value:
                    summed[key] += value
                    seen = True
        if seen:
            counts = summed
    return counts


def build_record(workflow: str, ctx: RunContext, numbers: dict, outcome: str,
                 reason: Optional[str], pr=None, head_sha=None, round_=0, verdict=None,
                 gate=None, now: Optional[datetime] = None) -> dict:
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
    cost = _num(numbers.get("total_cost_usd"))
    turns = _int(numbers.get("num_turns"))
    duration = _int(numbers.get("duration_ms"))
    if numbers:
        cost, turns, duration = (keep("cost_usd", cost), keep("turns", turns),
                                 keep("duration_ms", duration))
        tokens = {k: keep(k, v) for k, v in tokens.items()}
    record = {
        "schema": SCHEMA,
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "workflow": keep("workflow", _choice(workflow, RECORDED)),
        "run_id": keep("run_id", _digits(ctx.run_id)),
        "attempt": keep("attempt", _digits(ctx.attempt)),
        "repo": keep("repo", _text(ctx.repo, _REPO_RE)),
        "issue": keep("issue", _digits(ctx.issue)) if ctx.issue is not None else None,
        "pr": keep("pr", _digits(pr)) if pr is not None else None,
        "project": (keep("project", _text(ctx.project, _PROJECT_RE)) if ctx.project else None),
        "login": keep("login", _choice(ctx.login, LOGINS)),
        "model": keep("model", _choice(ctx.model, claude.MODELS)),
        "budget": keep("budget", _budget(ctx.budget)),
        "model_ids": model_ids,
        "claude_code_version": keep("claude_code_version",
                                    _text(ctx.claude_code_version, _VERSION_RE)),
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
        if reason in REASONS or subtype_reason(reason):
            record["reason"] = reason
        else:
            warn.bad("reason")
    return record


def failure_reason(outcomes: Outcomes, numbers: dict, unchanged: bool = False,
                   review: bool = False) -> Optional[str]:
    """Why a run failed, from how its steps ended and the numbers its agent left. Only values
    from the fixed lists, or a checked CLI error subtype. None when nothing establishes it.

    `unchanged`: publish found nothing to commit. `review`: the agent's answer is findings
    to parse, so a clean result line with no usable answer is `unparsed-findings`."""
    if "cancelled" in (outcomes.job, outcomes.agent, outcomes.check, outcomes.publish):
        return "cancelled"
    if outcomes.agent != "success":
        subtype = numbers.get("subtype")
        if subtype_reason(subtype):
            return subtype
        if review and subtype == "success" and numbers.get("is_error") is not True:
            return "unparsed-findings"
        return "no-result"
    if outcomes.check == "failure":
        return "check-failed"
    if not outcomes.publish:
        return None
    return "no-change" if unchanged else "publish-failed"


# ---- the marker ------------------------------------------------------------------

def marker(record: dict) -> str:
    return MARKER_START + json.dumps(record, separators=(",", ":")) + MARKER_END


def marker_line(record: dict) -> Optional[str]:
    """The marker, after one last check of the whole serialized line: nothing that could close
    the HTML comment and nothing token-shaped. None, with a warning, when it fails."""
    line = marker(record)
    if UNSAFE_RE.search(line[len(MARKER_START):-len(MARKER_END)]):
        print("::warning title=Run record::the record's line failed its last check; "
              "no marker is posted")
        return None
    return line


def record_text(body) -> Optional[str]:
    """The JSON of the Run record in a comment, or None. A marker counts only as the whole
    final line of the comment, where the factory's last step writes it: a copy in the middle
    of the text is somebody's quotation."""
    if not isinstance(body, str):
        return None
    lines = body.rstrip().split("\n")
    found = _MARKER_LINE_RE.fullmatch(lines[-1].strip())
    return found.group(1) if found else None


def has_record(body) -> bool:
    return record_text(body) is not None


# ---- what the writers share ------------------------------------------------------

def bot_comments(comments: List[dict], app_slug: str, unrecorded: bool = True) -> List[dict]:
    """The factory bot's own comments, by default only those that hold no record yet."""
    return [c for c in comments
            if isinstance(c.get("body"), str) and not (unrecorded and has_record(c["body"]))
            and is_factory_app(str((c.get("user") or {}).get("login", "")), app_slug)]


def opened_pr(body: str, repo: str, prefix: str) -> Optional[int]:
    """The pull request number in an "opened a draft PR" comment (`prefix` + its URL)."""
    found = re.match(re.escape(prefix) + PR_URL.format(repo=re.escape(repo)), body or "")
    return int(found.group(1)) if found else None


COMMENT_LIMIT = 65536      # characters in one GitHub comment


def leave_record(gh: GitHub, repo: str, number: int, out: Path, record: dict, text: str,
                 target: Optional[dict] = None) -> None:
    """Write <out>/run.json, then put the marker on the run's comment (`target`) or, with
    none, on a new comment on `number` that says `text`. A failed post is a warning."""
    (out / "run.json").write_text(json.dumps(record, indent=2) + "\n")
    line = marker_line(record)
    try:
        if target:
            if line:
                body = target["body"].rstrip("\n") + "\n" + line + "\n"
                if len(body) > COMMENT_LIMIT:      # GitHub would refuse it: the record stands alone
                    gh.comment(repo, number, write_comment(out, "run-comment.md", line + "\n"))
                else:
                    gh.update_comment(repo, target["id"],
                                      write_comment(out, "run-comment.md", body))
        else:
            body = text + "\n" + (line + "\n" if line else "")
            gh.comment(repo, number, write_comment(out, "run-comment.md", body))
    except GitHubError as e:
        print(f"::warning title=Run record::could not post the record: {e}")
    print(f"Run record: {record['outcome']}"
          + (f" ({record['reason']})" if record["reason"] else ""))
