"""The Bench's tracer: one Bench run scores one Bench case and stops at the ledger
(GLOSSARY.md, docs/adr/0009-bench-spends-on-a-metered-api-key.md).

  uv run python -m factory.bench --case CASE.json --setup-id ID --harness-command CMD --review-answer-file tests/factory/review-answer.json

CASE.json names the Bench case: {"repo": PATH, "start_commit": SHA, "ticket": PATH,
"check_command": CMD, "check_files": {PATH: BLOB_SHA}, "issue": N, "project": NAME|null}.

The run clones the start commit into a fresh directory outside the source
checkout, removes the remote, runs the harness command (the stand-in) there,
scores the check, runs Review through factory.review_pr.parse_findings, and
appends one JSON line to <out>/ledger.jsonl. No model call and no GitHub call.
`--review-answer-file` is the recorded Review answer. Tests may inject an agent
instead. With neither, the command exits 2 and writes no line.

This ticket is one Bench run, so the line records model sonnet and repeat 1.
The Setup id and the harness command are the arguments. The month is UTC, read
from the line's ts. A crashed stand-in records the case as fail and check as
skipped, and does not call Review.

The lock file is the open reservation: one run at a time, holding only the
holder's pid. A live holder blocks the next start. A holder whose process is
gone is released, and that reservation is not kept. The dollar check runs at
each start against the lines already written. The command exits 0 when the line
is written, even for a failed case, and non-zero when the ledger refuses.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Tuple

from factory import claude, review_pr

SCHEMA = 1
LOGIN = "anthropic-api"
COST_NOTE = "client-estimate"
PASS = "PASS"
# Never in the stand-in's environment (docs/adr/0009-bench-spends-on-a-metered-api-key.md).
_DROPPED = claude._DROPPED + ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")


class LedgerRefused(RuntimeError):
    """The ledger will not start this run."""


@dataclass(frozen=True)
class Limits:
    """Dollars. The month is UTC; the reservation is the build cap plus the review cap."""
    monthly_cap_usd: float = 100.0
    build_cap_usd: float = 2.0
    review_cap_usd: float = 1.0

    @property
    def reservation_usd(self) -> float:
        return self.build_cap_usd + self.review_cap_usd


# ---- ledger ----------------------------------------------------------------

def month_of(ts: str) -> str:
    """The UTC month of an ISO timestamp written by this module."""
    return ts[:7]


def spent_usd(ledger: Path, month: str) -> float:
    if not ledger.exists():
        return 0.0
    total = 0.0
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if month_of(row.get("ts", "")) == month:
            total += float(row.get("build_cost_usd") or 0) + float(row.get("review_cost_usd") or 0)
    return total


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire(out: Path, limits: Limits, now: datetime) -> Path:
    """Take the one-run lock, then refuse when this month's remainder is below
    the reservation.

    The lock is the open reservation and records the holder's pid. A live holder
    blocks the next start. A holder whose process is gone is released, so the
    reservation is not kept. The dollar check runs at each start against lines
    already written, so a run that spends the cap still writes its line and the
    next start is refused. Raises LedgerRefused.
    """
    lock = out / "ledger.lock"
    for _ in range(2):
        tmp = out / f"ledger.lock.{os.getpid()}"
        tmp.write_text(json.dumps({"pid": os.getpid()}))
        try:
            os.link(tmp, lock)  # atomic: the lock never exists empty
        except FileExistsError:
            try:
                pid = int(json.loads(lock.read_text()).get("pid", 0))
            except (ValueError, OSError):
                pid = 0
            if pid and _alive(pid):
                raise LedgerRefused(f"another Bench run (pid {pid}) holds the lock")
            lock.unlink(missing_ok=True)
            continue
        finally:
            tmp.unlink(missing_ok=True)
        break
    else:
        raise LedgerRefused("could not take the ledger lock")
    remaining = limits.monthly_cap_usd - spent_usd(out / "ledger.jsonl", month_of(now.isoformat()))
    if remaining < limits.reservation_usd:
        lock.unlink(missing_ok=True)
        raise LedgerRefused(f"${remaining:.2f} remains this month, below the "
                            f"${limits.reservation_usd:.2f} reservation")
    return lock


# ---- the run ---------------------------------------------------------------

def standin_env(step_env: Mapping[str, str], ticket: Path, result: Path, model: str,
                budget: float) -> dict:
    env = {k: v for k, v in step_env.items() if k not in _DROPPED}
    env.update({"BENCH_TICKET": str(ticket), "BENCH_RESULT": str(result),
                "BENCH_MODEL": model, "BENCH_BUDGET": f"{budget:g}"})
    return env


def secrets(step_env: Mapping[str, str]) -> List[str]:
    return [v for k, v in step_env.items() if len(v or "") >= 8 and k in _DROPPED]


def _git(*args: str, cwd: Path) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout.strip()


def scratch_clone(repo: str, start: str, source_root: Path) -> Path:
    dest = Path(tempfile.mkdtemp(prefix="bench-")).resolve()
    if dest.is_relative_to(source_root.resolve()):
        shutil.rmtree(dest, ignore_errors=True)
        raise RuntimeError(f"the scratch directory {dest} is inside the source checkout")
    try:
        _git("clone", "--quiet", str(Path(repo).resolve()), str(dest), cwd=dest)
        _git("checkout", "--quiet", "--detach", start, cwd=dest)
        for remote in _git("remote", cwd=dest).split():
            _git("remote", "remove", remote, cwd=dest)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


def read_standin_result(path: Path) -> Optional[dict]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def score_check(clone: Path, case: dict, env: dict) -> str:
    """pass | fail | tampered. A check file that differs from its recorded blob
    means the check is not executed."""
    for rel, blob in (case.get("check_files") or {}).items():
        target = clone / rel
        if not target.is_file() or _git("hash-object", rel, cwd=clone) != blob:
            return "tampered"
    try:
        p = subprocess.run(shlex.split(case["check_command"]), cwd=clone, env=env,
                           capture_output=True, text=True)
    except OSError:
        return "fail"
    return "pass" if p.returncode == 0 else "fail"


def review_case(case: dict, clone: Path, run_dir: Path, start: str, setup: dict,
                limits: Limits, run_agent: Callable) -> Tuple[str, float]:
    """(verdict, cost). The verdict is PASS, BLOCKED (as review_pr names it) or error; an unparseable
    answer is not retried."""
    _git("add", "-A", cwd=clone)
    (run_dir / "diff.patch").write_text(_git("diff", "--cached", "--no-color", start, cwd=clone) + "\n")
    ctx = {"repo": "bench", "pr": start[:12], "base_sha": start,
           "head_sha": _git("rev-parse", "HEAD", cwd=clone), "code_dir": str(clone),
           "ticket": case.get("issue")}
    try:
        result = run_agent(review_pr.build_prompt(ctx, run_dir), login=LOGIN,
                           model=setup["review_model"], max_budget_usd=limits.review_cap_usd,
                           cwd=str(clone), transcript=run_dir / "review.jsonl",
                           disallowed_tools=review_pr.DENIED_TOOLS,
                           allowed_tools=review_pr.READ_TOOLS)
    except Exception as e:  # the agent's failure is a Review error; keep the trace
        (run_dir / "review-error.txt").write_text(f"{type(e).__name__}: {e}\n")
        return "error", limits.review_cap_usd
    cost = result.cost_usd if result.cost_usd is not None else limits.review_cap_usd
    if not result.success:
        return "error", cost
    try:
        findings = review_pr.parse_findings(result.text)
    except (ValueError, KeyError, TypeError, AttributeError):
        return "error", cost
    return ("BLOCKED" if findings.blocker else PASS), cost


def run_standin(setup: dict, clone: Path, env: dict, run_dir: Path,
                result_path: Path) -> Tuple[bool, dict]:
    """(crashed, what the stand-in reported). A crash is a non-zero exit, or a
    result that is missing or not ok."""
    try:
        with (run_dir / "standin.log").open("w") as log:
            proc = subprocess.run(shlex.split(setup["harness_command"]), cwd=clone, env=env,
                                  stdout=log, stderr=subprocess.STDOUT)
        crashed = proc.returncode != 0
    except OSError:
        crashed = True
    reported = read_standin_result(result_path)
    return crashed or not reported or reported.get("ok") is not True, reported or {}


def bench_run(case: dict, setup: dict, out: Path, limits: Limits, run_agent: Callable,
              source_root: Path, step_env: Optional[Mapping[str, str]] = None,
              now: Optional[datetime] = None) -> dict:
    """One Bench run. Raises LedgerRefused before anything starts."""
    step_env = os.environ if step_env is None else step_env
    now = now or datetime.now(timezone.utc)
    out.mkdir(parents=True, exist_ok=True)
    lock = acquire(out, limits, now)
    clone = None
    try:
        (out / "runs").mkdir(exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(prefix=now.strftime("%Y%m%dT%H%M%S-"), dir=out / "runs"))
        start = case["start_commit"]
        ticket = run_dir / "ticket.md"
        ticket.write_text(Path(case["ticket"]).read_text())
        result_path = run_dir / "result.json"
        clone = scratch_clone(case["repo"], start, source_root)
        env = standin_env(step_env, ticket, result_path, setup["model"], limits.build_cap_usd)

        began = time.monotonic()
        crashed, reported = run_standin(setup, clone, env, run_dir, result_path)
        cost = reported.get("cost_usd")
        build_cost = float(cost) if isinstance(cost, (int, float)) else limits.build_cap_usd

        check = "skipped"
        verdict, review_cost = None, 0.0
        if not crashed:
            check = score_check(clone, case, env)
            verdict, review_cost = review_case(case, clone, run_dir, start, setup, limits, run_agent)
        row = {
            "schema": SCHEMA, "ts": now.isoformat(), "workflow": "bench", "pr": None,
            "outcome": "pass" if check == "pass" and verdict == PASS else "fail",
            "login": LOGIN, "cost_note": COST_NOTE,
            "issue": case.get("issue"), "project": case.get("project"),
            "model": setup["model"], "budget": limits.build_cap_usd,
            "build_cost_usd": build_cost, "review_cost_usd": review_cost,
            "turns": reported.get("num_turns"),
            "duration_ms": (reported["duration_ms"] if reported.get("duration_ms") is not None
                            else int((time.monotonic() - began) * 1000)),
            "input_tokens": reported.get("input_tokens"),
            "output_tokens": reported.get("output_tokens"),
            "cache_creation_input_tokens": reported.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": reported.get("cache_read_input_tokens"),
            "start_commit": start, "head_sha": _git("rev-parse", "HEAD", cwd=clone),
            "setup_id": setup["setup_id"], "repeat": setup.get("repeat", 1),
            "check": check, "review": verdict,
        }
        with (out / "ledger.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
        return row
    finally:
        if clone is not None:
            shutil.rmtree(clone, ignore_errors=True)
        claude.scrub(out, secrets(step_env))
        lock.unlink(missing_ok=True)


def recorded_review(text: str) -> Callable:
    """The owner's Review agent: a recorded answer, and no model call."""
    def run_agent(prompt, **_):
        return claude.Result(True, text, "success", 0.0)
    return run_agent


def main(argv: Optional[List[str]] = None, run_agent: Optional[Callable] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--case", required=True, help="the Bench case's JSON file")
    p.add_argument("--setup-id", required=True)
    p.add_argument("--harness-command", required=True)
    p.add_argument("--review-answer-file",
                   help="a recorded Review answer; the command calls no model")
    p.add_argument("--out", default="bench-runs")
    p.add_argument("--monthly-cap-usd", type=float, default=Limits.monthly_cap_usd)
    p.add_argument("--build-cap-usd", type=float, default=Limits.build_cap_usd)
    p.add_argument("--review-cap-usd", type=float, default=Limits.review_cap_usd)
    args = p.parse_args(argv)
    if run_agent is None:
        if not args.review_answer_file:
            print("bench: pass --review-answer-file, or inject Review's agent; "
                  "this command does not call a model", file=sys.stderr)
            return 2
        answer = Path(args.review_answer_file)
        try:
            text = answer.read_text()
        except OSError as e:
            print(f"bench: cannot read {answer}: {e}", file=sys.stderr)
            return 2
        run_agent = recorded_review(text)
    case = json.loads(Path(args.case).read_text())
    # One Bench run records model sonnet and repeat 1. The Setup id and the
    # harness command are the arguments above.
    setup = {"setup_id": args.setup_id, "harness_command": args.harness_command,
             "model": "sonnet", "review_model": "sonnet", "repeat": 1}
    limits = Limits(args.monthly_cap_usd, args.build_cap_usd, args.review_cap_usd)
    try:
        row = bench_run(case, setup, Path(args.out), limits, run_agent,
                        Path(__file__).resolve().parent.parent)
    except LedgerRefused as e:
        print(f"bench: the ledger refuses: {e}", file=sys.stderr)
        return 1
    print(json.dumps(row))
    left = limits.monthly_cap_usd - spent_usd(Path(args.out) / "ledger.jsonl", month_of(row["ts"]))
    if left < limits.reservation_usd:
        print(f"bench: ${left:.2f} remains, below the ${limits.reservation_usd:.2f} "
              "reservation; the next run will be refused", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
