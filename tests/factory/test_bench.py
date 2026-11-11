"""The Bench tracer: one Bench run on a fixture, no model call, no GitHub call."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from factory import bench, claude

SOURCE = Path(bench.__file__).resolve().parent.parent
PASS_ANSWER = json.dumps({"spec_summary": "ok", "standards_summary": "ok",
                          "spec_findings": [], "standards_findings": []})
NOTES_ANSWER = json.dumps({"spec_summary": "ok", "standards_summary": "n",
                           "spec_findings": [],
                           "standards_findings": [{"kind": "baseline_smell", "description": "d",
                                                   "resolution": "r"}]})
BLOCK_ANSWER = json.dumps({"spec_summary": "no", "standards_summary": "ok",
                           "spec_findings": [{"kind": "missing_requirement", "description": "d",
                                              "resolution": "r"}],
                           "standards_findings": []})


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def fixture(tmp_path):
    repo = tmp_path / "fixture"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    (repo / "check.py").write_text("import sys, pathlib\n"
                                   "sys.exit(0 if pathlib.Path('done.txt').exists() else 1)\n")
    (repo / "README").write_text("tiny\n")
    git("add", "-A", cwd=repo)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start", cwd=repo)
    ticket = tmp_path / "ticket.md"
    ticket.write_text("# Make done.txt\n")
    case = {"repo": str(repo), "start_commit": git("rev-parse", "HEAD", cwd=repo),
            "ticket": str(ticket), "issue": 7, "project": None,
            "check_command": f"{sys.executable} check.py",
            "check_files": {"check.py": git("hash-object", "check.py", cwd=repo)}}
    return case


def standin(tmp_path, body, name="standin.py"):
    script = tmp_path / name
    script.write_text("import json, os, pathlib\n" + textwrap.dedent(body))
    return f"{sys.executable} {script}"


WRITE_RESULT = """
r = {"ok": True, "summary": "", "input_tokens": 1, "output_tokens": 2,
     "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
     "cost_usd": %s, "num_turns": 3, "duration_ms": 5, "model": "sonnet"}
pathlib.Path(os.environ["BENCH_RESULT"]).write_text(json.dumps(r))
"""
GOOD = "pathlib.Path('done.txt').write_text('x')\n" + WRITE_RESULT % "0.5"
NOOP = WRITE_RESULT % "0.5"


def agent(answer, calls=None):
    def run(prompt, **kw):
        if calls is not None:
            calls.append(prompt)
        return claude.Result(True, answer, "success", 0.25)
    return run


def run(case, tmp_path, command, answer=PASS_ANSWER, calls=None, limits=None, out=None, env=None):
    setup = {"setup_id": "s1", "harness_command": command, "model": "sonnet",
             "review_model": "sonnet", "repeat": 1}
    return bench.bench_run(case, setup, out or tmp_path / "out", limits or bench.Limits(),
                           agent(answer, calls), SOURCE, step_env=env or {})


def test_tracer_pass_line(fixture, tmp_path):
    row = run(fixture, tmp_path, standin(tmp_path, GOOD))
    assert row["outcome"] == "pass" and row["workflow"] == "bench" and row["pr"] is None
    assert row["schema"] == 1 and row["login"] == "anthropic-api"
    assert row["cost_note"] == "client-estimate" and row["check"] == "pass"
    assert row["review"] == "PASS" and row["build_cost_usd"] == 0.5 and row["turns"] == 3
    lines = (tmp_path / "out" / "ledger.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0]) == row
    assert not (tmp_path / "out" / "ledger.lock").exists()


def test_tracer_standards_notes_keep_pass(fixture, tmp_path):
    assert run(fixture, tmp_path, standin(tmp_path, GOOD), NOTES_ANSWER)["outcome"] == "pass"


def test_tracer_noop_standin_fails_on_missing_requirement(fixture, tmp_path):
    row = run(fixture, tmp_path, standin(tmp_path, NOOP), BLOCK_ANSWER)
    assert row["outcome"] == "fail" and row["review"] == "BLOCKER"


def test_tracer_noop_standin_fails_check(fixture, tmp_path):
    row = run(fixture, tmp_path, standin(tmp_path, NOOP))
    assert row["check"] == "fail" and row["outcome"] == "fail"


def test_tracer_tampered_check_not_executed(fixture, tmp_path):
    marker = tmp_path / "ran"
    evil = f"import pathlib; pathlib.Path({str(marker)!r}).write_text('x')"
    script = f"pathlib.Path('check.py').write_text({evil!r})\n"
    calls = []
    row = run(fixture, tmp_path, standin(tmp_path, script + GOOD), calls=calls)
    assert row["check"] == "tampered" and row["outcome"] == "fail"
    assert not marker.exists() and len(calls) == 1


def test_tracer_crash_skips_review(fixture, tmp_path):
    calls = []
    row = run(fixture, tmp_path, standin(tmp_path, "raise SystemExit(3)\n"), calls=calls)
    assert row["outcome"] == "fail" and row["review"] is None and calls == []
    assert row["build_cost_usd"] == 2.0


def test_tracer_unparseable_review_is_error_and_not_retried(fixture, tmp_path):
    calls = []
    row = run(fixture, tmp_path, standin(tmp_path, GOOD), "not json", calls=calls)
    assert row["review"] == "error" and row["outcome"] == "fail" and len(calls) == 1


def test_tracer_standin_env_and_scratch_clone(fixture, tmp_path):
    seen = tmp_path / "seen.json"
    script = f"""
import subprocess
d = {{k: os.environ.get(k) for k in ("GH_TOKEN","GITHUB_TOKEN","CLAUDE_CODE_OAUTH_TOKEN",
      "OPENROUTER_API_KEY","FACTORY_OPENROUTER_KEY","ANTHROPIC_API_KEY","BENCH_TICKET",
      "BENCH_RESULT","BENCH_MODEL","BENCH_BUDGET")}}
d["cwd"] = os.getcwd()
d["remotes"] = subprocess.run(["git","remote"],capture_output=True,text=True).stdout
pathlib.Path({str(seen)!r}).write_text(json.dumps(d))
"""
    env = {k: "secretvalue123" for k in ("GH_TOKEN", "GITHUB_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
                                         "OPENROUTER_API_KEY", "FACTORY_OPENROUTER_KEY",
                                         "ANTHROPIC_API_KEY")}
    env["PATH"] = os.environ["PATH"]
    run(fixture, tmp_path, standin(tmp_path, script + GOOD), env=env)
    d = json.loads(seen.read_text())
    for k in ("GH_TOKEN", "GITHUB_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY",
              "FACTORY_OPENROUTER_KEY", "ANTHROPIC_API_KEY"):
        assert d[k] is None
    assert d["BENCH_MODEL"] == "sonnet" and d["BENCH_BUDGET"] == "2"
    assert d["BENCH_TICKET"] and d["BENCH_RESULT"]
    clone = Path(d["cwd"]).resolve()
    assert d["remotes"].strip() == ""
    assert not clone.is_relative_to(SOURCE) and not clone.exists()


def test_tracer_ledger_refuses_second_run(fixture, tmp_path):
    limits = bench.Limits(monthly_cap_usd=0.30, build_cap_usd=0.02, review_cap_usd=0.01)
    null_cost = standin(tmp_path, "pathlib.Path('done.txt').write_text('x')\n"
                        + WRITE_RESULT % "None")
    row = run(fixture, tmp_path, null_cost, limits=limits)
    assert row["build_cost_usd"] == 0.02 and row["review_cost_usd"] == 0.25
    out = tmp_path / "out"
    before = (out / "ledger.jsonl").read_text()
    with pytest.raises(bench.LedgerRefused):
        run(fixture, tmp_path, null_cost, limits=limits)
    assert (out / "ledger.jsonl").read_text() == before


def test_tracer_cli_exit_codes(fixture, tmp_path):
    case = tmp_path / "case.json"
    case.write_text(json.dumps(fixture))
    answer = tmp_path / "answer.txt"
    answer.write_text(BLOCK_ANSWER)
    argv = ["--case", str(case), "--setup-id", "s", "--harness-command",
            standin(tmp_path, NOOP), "--review-answer", str(answer), "--out", str(tmp_path / "o"),
            "--monthly-cap-usd", "3", "--build-cap-usd", "2", "--review-cap-usd", "1"]
    assert bench.main(argv) == 0  # a failed case still exits 0
    assert json.loads((tmp_path / "o" / "ledger.jsonl").read_text())["outcome"] == "fail"
    argv[argv.index("3")] = "3.5"
    # 0.5 spent of 3.5 leaves 3.0: still enough; then 1.0 spent leaves 2.5: refused
    assert bench.main(argv) == 0
    assert bench.main(argv) == 1
    assert len((tmp_path / "o" / "ledger.jsonl").read_text().splitlines()) == 2


def test_tracer_dead_lock_holder_releases_reservation(fixture, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (out / "ledger.lock").write_text(json.dumps({"pid": dead.pid, "reservation_usd": 3.0}))
    limits = bench.Limits(monthly_cap_usd=3.0)
    assert run(fixture, tmp_path, standin(tmp_path, GOOD), limits=limits)["outcome"] == "pass"


def test_tracer_live_lock_holder_refuses(fixture, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "ledger.lock").write_text(json.dumps({"pid": os.getpid()}))
    with pytest.raises(bench.LedgerRefused):
        run(fixture, tmp_path, standin(tmp_path, GOOD))


def test_tracer_secrets_scrubbed(fixture, tmp_path):
    script = "print(os.environ.get('BENCH_MODEL'))\nprint('leak', 'hunter2hunter2')\n" + GOOD
    run(fixture, tmp_path, standin(tmp_path, script), env={"GH_TOKEN": "hunter2hunter2"})
    assert "hunter2hunter2" not in (tmp_path / "out" / "runs").rglob("standin.log").__next__().read_text()
