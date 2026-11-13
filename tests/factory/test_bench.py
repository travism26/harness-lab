"""The Bench tracer: one Bench run on a Bench case, no model call, no GitHub call."""

import hashlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from factory import bench, claude, ticket

SOURCE = Path(bench.__file__).resolve().parent.parent
REVIEW_ANSWER = Path(__file__).with_name("review-answer.json")
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
def bench_case(tmp_path):
    repo = tmp_path / "case-repo"
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


def test_tracer_pass_line(bench_case, tmp_path):
    row = run(bench_case, tmp_path, standin(tmp_path, GOOD))
    assert row["outcome"] == "pass" and row["workflow"] == "bench" and row["pr"] is None
    assert row["schema"] == 1 and row["login"] == "anthropic-api"
    assert row["cost_note"] == "client-estimate" and row["check"] == "pass"
    assert row["review"] == "PASS" and row["build_cost_usd"] == 0.5 and row["turns"] == 3
    assert row["model"] == "sonnet" and row["setup_id"] == "s1" and row["repeat"] == 1
    assert row["budget"] == 2 and row["issue"] == 7 and row["duration_ms"] == 5
    assert row["start_commit"] == bench_case["start_commit"] and row["head_sha"]
    assert row["input_tokens"] == 1 and row["output_tokens"] == 2
    lines = (tmp_path / "out" / "ledger.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0]) == row
    assert not (tmp_path / "out" / "ledger.lock").exists()


def test_tracer_standards_notes_keep_pass(bench_case, tmp_path):
    assert run(bench_case, tmp_path, standin(tmp_path, GOOD), NOTES_ANSWER)["outcome"] == "pass"


def test_tracer_noop_standin_fails_on_missing_requirement(bench_case, tmp_path):
    row = run(bench_case, tmp_path, standin(tmp_path, NOOP), BLOCK_ANSWER)
    assert row["outcome"] == "fail" and row["review"] == "BLOCKED"


def test_tracer_noop_standin_fails_check(bench_case, tmp_path):
    row = run(bench_case, tmp_path, standin(tmp_path, NOOP))
    assert row["check"] == "fail" and row["outcome"] == "fail"


def test_tracer_tampered_check_not_executed(bench_case, tmp_path):
    marker = tmp_path / "ran"
    evil = f"import pathlib; pathlib.Path({str(marker)!r}).write_text('x')"
    script = f"pathlib.Path('check.py').write_text({evil!r})\n"
    calls = []
    row = run(bench_case, tmp_path, standin(tmp_path, script + GOOD), calls=calls)
    assert row["check"] == "tampered" and row["outcome"] == "fail"
    assert not marker.exists() and len(calls) == 1


def test_tracer_crash_skips_review(bench_case, tmp_path):
    calls = []
    row = run(bench_case, tmp_path, standin(tmp_path, "raise SystemExit(3)\n"), calls=calls)
    assert row["outcome"] == "fail" and row["check"] == "skipped" and row["review"] is None
    assert calls == [] and row["build_cost_usd"] == 2.0


def test_tracer_unparseable_review_is_error_and_not_retried(bench_case, tmp_path):
    calls = []
    row = run(bench_case, tmp_path, standin(tmp_path, GOOD), "not json", calls=calls)
    assert row["review"] == "error" and row["outcome"] == "fail" and len(calls) == 1


def test_tracer_standin_env_and_scratch_clone(bench_case, tmp_path):
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
    run(bench_case, tmp_path, standin(tmp_path, script + GOOD), env=env)
    d = json.loads(seen.read_text())
    for k in ("GH_TOKEN", "GITHUB_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY",
              "FACTORY_OPENROUTER_KEY", "ANTHROPIC_API_KEY"):
        assert d[k] is None
    assert d["BENCH_MODEL"] == "sonnet" and d["BENCH_BUDGET"] == "2"
    assert d["BENCH_TICKET"] and d["BENCH_RESULT"]
    clone = Path(d["cwd"]).resolve()
    assert d["remotes"].strip() == ""
    assert not clone.is_relative_to(SOURCE) and not clone.exists()


def test_tracer_ledger_refuses_second_run(bench_case, tmp_path):
    limits = bench.Limits(monthly_cap_usd=0.30, build_cap_usd=0.02, review_cap_usd=0.01)
    null_cost = standin(tmp_path, "pathlib.Path('done.txt').write_text('x')\n"
                        + WRITE_RESULT % "None")
    row = run(bench_case, tmp_path, null_cost, limits=limits)
    assert row["build_cost_usd"] == 0.02 and row["review_cost_usd"] == 0.25
    out = tmp_path / "out"
    before = (out / "ledger.jsonl").read_text()
    with pytest.raises(bench.LedgerRefused):
        run(bench_case, tmp_path, null_cost, limits=limits)
    assert (out / "ledger.jsonl").read_text() == before


def test_tracer_cli_exit_codes(bench_case, tmp_path):
    case = tmp_path / "case.json"
    case.write_text(json.dumps(bench_case))
    out = tmp_path / "o"
    argv = ["--case", str(case), "--setup-id", "s", "--harness-command",
            standin(tmp_path, NOOP), "--out", str(out),
            "--monthly-cap-usd", "3", "--build-cap-usd", "2", "--review-cap-usd", "1"]

    def review(prompt, **_kw):
        return claude.Result(True, BLOCK_ANSWER, "success", 0.0)

    assert bench.main(argv) == 2  # no injected agent, and no recorded answer to replay
    assert not (out / "ledger.jsonl").exists()
    assert bench.main(argv, run_agent=review) == 0  # a failed case still exits 0
    assert json.loads((out / "ledger.jsonl").read_text())["outcome"] == "fail"
    argv[argv.index("3")] = "3.5"
    # 0.5 spent of 3.5 leaves 3.0: still enough; then 1.0 spent leaves 2.5: refused
    assert bench.main(argv, run_agent=review) == 0
    assert bench.main(argv, run_agent=review) == 1
    assert len((out / "ledger.jsonl").read_text().splitlines()) == 2


def test_tracer_owner_command_writes_one_line(bench_case, tmp_path):
    """The real command, with the shipped answer file and no injected agent."""
    case = tmp_path / "case.json"
    case.write_text(json.dumps(bench_case))
    out = tmp_path / "o"
    code = bench.main(["--case", str(case), "--setup-id", "owner",
                       "--harness-command", standin(tmp_path, GOOD),
                       "--review-answer-file", str(REVIEW_ANSWER),
                       "--out", str(out)])
    assert code == 0
    lines = (out / "ledger.jsonl").read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["outcome"] == "pass" and row["workflow"] == "bench" and row["pr"] is None
    assert row["review"] == "PASS"


def test_tracer_dead_lock_holder_releases_reservation(bench_case, tmp_path):
    """The cap equals one reservation and nothing is spent. The run starts only
    because the dead holder's lock was released; leaving that lock held refuses."""
    out = tmp_path / "out"
    out.mkdir()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (out / "ledger.lock").write_text(json.dumps({"pid": dead.pid}))
    limits = bench.Limits(monthly_cap_usd=3.0)
    row = run(bench_case, tmp_path, standin(tmp_path, GOOD), limits=limits)
    assert row["outcome"] == "pass"
    assert not (out / "ledger.lock").exists()
    assert len((out / "ledger.jsonl").read_text().splitlines()) == 1


def test_tracer_live_lock_holder_refuses(bench_case, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "ledger.lock").write_text(json.dumps({"pid": os.getpid()}))
    with pytest.raises(bench.LedgerRefused):
        run(bench_case, tmp_path, standin(tmp_path, GOOD))


def test_tracer_secrets_scrubbed(bench_case, tmp_path):
    script = "print(os.environ.get('BENCH_MODEL'))\nprint('leak', 'hunter2hunter2')\n" + GOOD
    run(bench_case, tmp_path, standin(tmp_path, script), env={"GH_TOKEN": "hunter2hunter2"})
    assert "hunter2hunter2" not in next((tmp_path / "out" / "runs").rglob("standin.log")).read_text()


def test_tracer_reported_zero_duration_is_kept(bench_case, tmp_path):
    script = GOOD.replace('"duration_ms": 5', '"duration_ms": 0')
    row = run(bench_case, tmp_path, standin(tmp_path, script))
    assert row["duration_ms"] == 0


# ---- replay ----------------------------------------------------------------

KEY_ENV = {"ANTHROPIC_API_KEY": "sk-test-key-value", "PATH": os.environ["PATH"]}
TICKET_8 = ("0cad2cd64fab12b191dfc98dde306c6b80ad7eae",
            "a7fdffb5ce4571fefa002c7690c746e0e7aec2094b732120d3004997b9078bb2")
TICKET_9 = ("7a0d2be0fd3c3e7ee310c5e03a020af1e54f56fd",
            "7d552b820c83c37610671d607616a46d6e17453e98b152f31670c1577c828fc5")


def fake_cases(bench_case, tmp_path):
    """Two case files on the fixture repo, in a cases directory."""
    d = tmp_path / "cases"
    d.mkdir()
    for n in (8, 9):
        (d / f"ticket-{n}.md").write_text(f"# t{n}\n\nbody\n")
        case = dict(bench_case, repo=bench_case["repo"], ticket=f"ticket-{n}.md", issue=n)
        (d / f"ticket-{n}.json").write_text(json.dumps(case))
    return d


def replay_main(tmp_path, cases, command, *extra, **kw):
    return bench.main(["--replay", "--out", str(tmp_path / "o"), *extra],
                      cases_dir=cases, harness_command=command, **kw)


def test_replay_committed_cases_match_the_record():
    cases = dict(bench.committed_cases())
    assert list(cases) == ["ticket-8", "ticket-9"]
    for name, (start, digest) in (("ticket-8", TICKET_8), ("ticket-9", TICKET_9)):
        case = bench.load_case(cases[name], SOURCE)
        assert case["start_commit"] == start
        text = Path(case["ticket"]).read_bytes()
        assert hashlib.sha256(text).hexdigest() == digest
        assert text.startswith(b"# ") and text.endswith(b"\n")
        assert case["check_command"] == "projects/harness/check"
        assert case["check_files"] == {"projects/harness/check":
                                       "5d15da0aa44619f0a283683445cbb9c5ef016b06"}
        assert case["project"] == "harness" and case["bootstrap"] is False
        assert Path(case["repo"]) == SOURCE


def test_replay_frozen_check_blob_is_the_start_commits_file():
    for name in ("ticket-8", "ticket-9"):
        case = bench.load_case(dict(bench.committed_cases())[name], SOURCE)
        got = subprocess.run(["git", "-C", str(SOURCE), "rev-parse",
                              f"{case['start_commit']}:projects/harness/check"],
                             capture_output=True, text=True)
        if got.returncode:
            pytest.skip("the start commit is not in this checkout")
        assert got.stdout.strip() == case["check_files"]["projects/harness/check"]


def test_replay_three_repeats_six_lines_and_report(bench_case, tmp_path, capsys):
    cases = fake_cases(bench_case, tmp_path)
    code = replay_main(tmp_path, cases, standin(tmp_path, GOOD),
                      run_agent=agent(PASS_ANSWER), step_env=KEY_ENV,
                      version_fn=lambda: "2.1.319")
    assert code == 0
    rows = [json.loads(l) for l in (tmp_path / "o" / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 6
    assert [r["issue"] for r in rows] == [8, 8, 8, 9, 9, 9]
    assert [r["repeat"] for r in rows] == [1, 2, 3, 1, 2, 3]
    assert {r["setup_id"] for r in rows} == {"claude-code-sonnet"}
    lines = capsys.readouterr().out.splitlines()
    assert "not comparable" in lines[0] and "newer checkout" in lines[0]
    text = "\n".join(lines)
    for step in ("ANTHROPIC_API_KEY", "monthly limit", "2.1.319", "cannot read a newer checkout"):
        assert step in text
    assert "ticket-8: passed 3 of 3, unstable no, cost min $0.75 median $0.75 max $0.75" in text
    assert "ticket-9: passed 3 of 3" in text


def test_replay_report_unstable_and_cost_statistics():
    def row(outcome, check, review, build, rev):
        return {"outcome": outcome, "check": check, "review": review,
                "build_cost_usd": build, "review_cost_usd": rev}
    stable = [row("pass", "pass", "PASS", 1.0, 0.5), row("pass", "pass", "PASS", 3.0, 0.5),
              row("pass", "pass", "PASS", 2.0, 0.5)]
    by_check = [row("pass", "pass", "PASS", 1, 0), row("fail", "fail", "PASS", 2, 0),
                row("pass", "pass", "PASS", 3, 0)]
    by_review = [row("pass", "pass", "PASS", 1, 0), row("fail", "pass", "BLOCKED", 1, 0),
                 row("fail", "pass", "BLOCKED", 1, 0)]
    text = bench.report("s", [("a", stable), ("b", by_check), ("c", by_review)])
    assert "a: passed 3 of 3, unstable no, cost min $1.50 median $2.50 max $3.50" in text
    assert "b: passed 2 of 3, unstable yes, cost min $1.00 median $2.00 max $3.00" in text
    assert "c: passed 1 of 3, unstable yes" in text
    assert "rank" not in text.lower()


def test_replay_missing_key_refuses_before_clone(bench_case, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bench, "scratch_clone", lambda *a: pytest.fail("cloned"))
    cases = fake_cases(bench_case, tmp_path)
    code = replay_main(tmp_path, cases, "true", step_env={"PATH": "/usr/bin"},
                      version_fn=lambda: "2.1.319")
    assert code != 0 and "ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_replay_wrong_version_refuses_with_install_line(bench_case, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bench, "scratch_clone", lambda *a: pytest.fail("cloned"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("ran a command"))
    cases = fake_cases(bench_case, tmp_path)
    for found in ("2.1.320", None):
        code = replay_main(tmp_path, cases, "true", step_env=KEY_ENV,
                          version_fn=lambda: found)
        err = capsys.readouterr().err
        assert code != 0 and "npm install -g @anthropic-ai/claude-code@2.1.319" in err
    assert not (tmp_path / "o").exists()


def test_replay_baseline_arguments_match_the_factory_command():
    args = bench.baseline_arguments(2.0)
    assert args == claude.command("sonnet", 2.0, None, ticket.DENIED_TOOLS, True)
    assert "--bare" not in args
    for flag in ("-p", "--verbose", "--setting-sources", "--disallowedTools", "--permission-mode"):
        assert flag in args
    assert args[args.index("--output-format") + 1] == "stream-json"
    assert args[args.index("--model") + 1] == "sonnet"
    setup = bench.baseline_setup(SOURCE)
    assert setup["setup_id"] == "claude-code-sonnet"
    assert setup["model"] == "sonnet" and setup["review_model"] == "sonnet"


def test_replay_defaults_hold_six_reservations():
    limits = bench.Limits()
    assert limits.monthly_cap_usd == 100 and limits.reservation_usd == 3
    assert limits.monthly_cap_usd // limits.reservation_usd >= 6


def test_replay_cap_of_five_reservations_writes_five_lines(bench_case, tmp_path, capsys):
    cases = fake_cases(bench_case, tmp_path)
    spend = standin(tmp_path, "pathlib.Path('done.txt').write_text('x')\n"
                    + WRITE_RESULT % "2.0")
    code = replay_main(tmp_path, cases, spend, "--monthly-cap-usd", "15",
                      run_agent=lambda prompt, **_: claude.Result(True, PASS_ANSWER, "success", 1.0),
                      step_env=KEY_ENV, version_fn=lambda: "2.1.319")
    assert code != 0
    lines = (tmp_path / "o" / "ledger.jsonl").read_text().splitlines()
    assert len(lines) == 5
    assert [json.loads(l)["repeat"] for l in lines] == [1, 2, 3, 1, 2]
    assert "ticket-9: passed 2 of 3" in capsys.readouterr().out


def test_replay_gives_the_harness_only_the_bench_key(bench_case, tmp_path):
    seen = tmp_path / "seen.json"
    script = (f"pathlib.Path({str(seen)!r}).write_text(json.dumps("
              "{k: os.environ.get(k) for k in ('ANTHROPIC_API_KEY','GH_TOKEN')}))\n") + GOOD
    cases = fake_cases(bench_case, tmp_path)
    env = dict(KEY_ENV, GH_TOKEN="ghtoken-value")
    replay_main(tmp_path, cases, standin(tmp_path, script),
               run_agent=agent(PASS_ANSWER), step_env=env, version_fn=lambda: "2.1.319")
    assert json.loads(seen.read_text()) == {"ANTHROPIC_API_KEY": "sk-test-key-value",
                                            "GH_TOKEN": None}
    assert "sk-test-key-value" not in "".join(
        p.read_text(errors="replace") for p in (tmp_path / "o").rglob("*") if p.is_file())
