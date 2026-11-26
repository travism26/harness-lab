"""The Bench tracer: one Bench run on a Bench case, no model call, no GitHub call."""

import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from factory import bench, claude, ticket

SOURCE = Path(bench.__file__).resolve().parent.parent
REVIEW_ANSWER = Path(__file__).with_name("review-answer.json")
PASS_ANSWER = json.dumps(
    {
        "spec_summary": "ok",
        "standards_summary": "ok",
        "spec_findings": [],
        "standards_findings": [],
    }
)
NOTES_ANSWER = json.dumps(
    {
        "spec_summary": "ok",
        "standards_summary": "n",
        "spec_findings": [],
        "standards_findings": [
            {"kind": "baseline_smell", "description": "d", "resolution": "r"}
        ],
    }
)
BLOCK_ANSWER = json.dumps(
    {
        "spec_summary": "no",
        "standards_summary": "ok",
        "spec_findings": [
            {"kind": "missing_requirement", "description": "d", "resolution": "r"}
        ],
        "standards_findings": [],
    }
)


def git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def bench_case(tmp_path):
    repo = tmp_path / "case-repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    (repo / "check.py").write_text(
        "import sys, pathlib\nsys.exit(0 if pathlib.Path('done.txt').exists() else 1)\n"
    )
    (repo / "README").write_text("tiny\n")
    git("add", "-A", cwd=repo)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start", cwd=repo)
    ticket = tmp_path / "ticket.md"
    ticket.write_text("# Make done.txt\n")
    case = {
        "repo": str(repo),
        "start_commit": git("rev-parse", "HEAD", cwd=repo),
        "ticket": str(ticket),
        "issue": 7,
        "project": None,
        "check_command": f"{sys.executable} check.py",
        "check_files": {"check.py": git("hash-object", "check.py", cwd=repo)},
    }
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


def run(
    case,
    tmp_path,
    command,
    answer=PASS_ANSWER,
    calls=None,
    limits=None,
    out=None,
    env=None,
):
    setup = {
        "setup_id": "s1",
        "harness_command": command,
        "model": "sonnet",
        "review_model": "sonnet",
        "repeat": 1,
    }
    return bench.bench_run(
        case,
        setup,
        out or tmp_path / "out",
        limits or bench.Limits(),
        agent(answer, calls),
        SOURCE,
        step_env=env or {},
    )


def test_tracer_pass_line(bench_case, tmp_path):
    row = run(bench_case, tmp_path, standin(tmp_path, GOOD))
    assert row["outcome"] == "pass" and row["workflow"] == "bench" and row["pr"] is None
    assert row["schema"] == 1 and row["login"] == "anthropic-api"
    assert row["cost_note"] == "client-estimate" and row["check"] == "pass"
    assert (
        row["review"] == "PASS" and row["build_cost_usd"] == 0.5 and row["turns"] == 3
    )
    assert row["model"] == "sonnet" and row["setup_id"] == "s1" and row["repeat"] == 1
    assert row["budget"] == 2 and row["issue"] == 7 and row["duration_ms"] == 5
    assert row["start_commit"] == bench_case["start_commit"] and row["head_sha"]
    assert row["input_tokens"] == 1 and row["output_tokens"] == 2
    lines = (tmp_path / "out" / "ledger.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0]) == row
    assert not (tmp_path / "out" / "ledger.lock").exists()


def test_tracer_standards_notes_keep_pass(bench_case, tmp_path):
    assert (
        run(bench_case, tmp_path, standin(tmp_path, GOOD), NOTES_ANSWER)["outcome"]
        == "pass"
    )


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
    row = run(
        bench_case, tmp_path, standin(tmp_path, "raise SystemExit(3)\n"), calls=calls
    )
    assert (
        row["outcome"] == "fail" and row["check"] == "skipped" and row["review"] is None
    )
    assert calls == [] and row["build_cost_usd"] == 2.0


def test_tracer_unparseable_review_is_retried_once(bench_case, tmp_path):
    answers = iter(["not json", PASS_ANSWER])
    seen = []

    def two_answers(prompt, **kw):
        seen.append(kw)
        kw["transcript"].write_text(f"run {len(seen)}")
        return claude.Result(True, next(answers), "success", 0.25)

    setup = {
        "setup_id": "s1",
        "harness_command": standin(tmp_path, GOOD),
        "model": "sonnet",
        "review_model": "sonnet",
        "repeat": 1,
    }
    row = bench.bench_run(
        bench_case,
        setup,
        tmp_path / "out",
        bench.Limits(),
        two_answers,
        SOURCE,
        step_env={},
    )
    assert row["review"] == "PASS" and row["outcome"] == "pass" and len(seen) == 2
    assert seen[1]["max_budget_usd"] == pytest.approx(
        bench.Limits().review_cap_usd - 0.25
    )
    assert row["review_cost_usd"] == pytest.approx(0.5)
    run_dir = next((tmp_path / "out" / "runs").iterdir())
    assert (run_dir / "review.jsonl").read_text() == "run 2"
    assert (run_dir / "review-unparsed.jsonl").read_text() == "run 1"


def test_tracer_review_unparseable_twice_is_error(bench_case, tmp_path):
    calls = []
    row = run(bench_case, tmp_path, standin(tmp_path, GOOD), "not json", calls=calls)
    assert row["review"] == "error" and row["outcome"] == "fail" and len(calls) == 2
    assert row["review_cost_usd"] == pytest.approx(0.5)


@pytest.mark.parametrize("error", [ValueError("bad cost"), TypeError("bad cost")])
def test_a_malformed_result_line_is_a_review_error_not_an_abort(
    bench_case, tmp_path, error
):
    def broken(prompt, **kw):
        raise error

    setup = {
        "setup_id": "s1",
        "harness_command": standin(tmp_path, GOOD),
        "model": "sonnet",
        "review_model": "sonnet",
        "repeat": 1,
    }
    row = bench.bench_run(
        bench_case, setup, tmp_path / "out", bench.Limits(), broken, SOURCE, step_env={}
    )
    assert row["review"] == "error" and row["outcome"] == "fail"


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
    env = {
        k: "secretvalue123"
        for k in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "OPENROUTER_API_KEY",
            "FACTORY_OPENROUTER_KEY",
            "ANTHROPIC_API_KEY",
        )
    }
    env["PATH"] = os.environ["PATH"]
    run(bench_case, tmp_path, standin(tmp_path, script + GOOD), env=env)
    d = json.loads(seen.read_text())
    for k in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "OPENROUTER_API_KEY",
        "FACTORY_OPENROUTER_KEY",
        "ANTHROPIC_API_KEY",
    ):
        assert d[k] is None
    assert d["BENCH_MODEL"] == "sonnet" and d["BENCH_BUDGET"] == "2"
    assert d["BENCH_TICKET"] and d["BENCH_RESULT"]
    clone = Path(d["cwd"]).resolve()
    assert d["remotes"].strip() == ""
    assert not clone.is_relative_to(SOURCE) and not clone.exists()


def test_tracer_ledger_refuses_second_run(bench_case, tmp_path):
    limits = bench.Limits(monthly_cap_usd=0.30, build_cap_usd=0.02, review_cap_usd=0.01)
    null_cost = standin(
        tmp_path, "pathlib.Path('done.txt').write_text('x')\n" + WRITE_RESULT % "None"
    )
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
    argv = [
        "--case",
        str(case),
        "--setup-id",
        "s",
        "--harness-command",
        standin(tmp_path, NOOP),
        "--out",
        str(out),
        "--monthly-cap-usd",
        "3",
        "--build-cap-usd",
        "2",
        "--review-cap-usd",
        "1",
    ]

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
    code = bench.main(
        [
            "--case",
            str(case),
            "--setup-id",
            "owner",
            "--harness-command",
            standin(tmp_path, GOOD),
            "--review-answer-file",
            str(REVIEW_ANSWER),
            "--out",
            str(out),
        ]
    )
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
    script = (
        "print(os.environ.get('BENCH_MODEL'))\nprint('leak', 'hunter2hunter2')\n" + GOOD
    )
    run(
        bench_case,
        tmp_path,
        standin(tmp_path, script),
        env={"GH_TOKEN": "hunter2hunter2"},
    )
    assert (
        "hunter2hunter2"
        not in next((tmp_path / "out" / "runs").rglob("standin.log")).read_text()
    )


def test_tracer_reported_zero_duration_is_kept(bench_case, tmp_path):
    script = GOOD.replace('"duration_ms": 5', '"duration_ms": 0')
    row = run(bench_case, tmp_path, standin(tmp_path, script))
    assert row["duration_ms"] == 0


# ---- replay ----------------------------------------------------------------

KEY_ENV = {"ANTHROPIC_API_KEY": "sk-test-key-value", "PATH": os.environ["PATH"]}
TICKET_8 = (
    "0cad2cd64fab12b191dfc98dde306c6b80ad7eae",
    "a7fdffb5ce4571fefa002c7690c746e0e7aec2094b732120d3004997b9078bb2",
)
TICKET_9 = (
    "7a0d2be0fd3c3e7ee310c5e03a020af1e54f56fd",
    "7d552b820c83c37610671d607616a46d6e17453e98b152f31670c1577c828fc5",
)


def fake_cases(bench_case, tmp_path):
    """Two case files on the fixture repo, in a cases directory."""
    d = tmp_path / "cases"
    d.mkdir()
    for n in (8, 9):
        (d / f"ticket-{n}.md").write_text(f"# t{n}\n\nbody\n")
        case = dict(
            bench_case, repo=bench_case["repo"], ticket=f"ticket-{n}.md", issue=n
        )
        (d / f"ticket-{n}.json").write_text(json.dumps(case))
    return d


def replay_main(tmp_path, cases, command, *extra, **kw):
    return bench.main(
        ["--replay", "--out", str(tmp_path / "o"), *extra],
        cases_dir=cases,
        harness_command=command,
        **kw,
    )


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
        assert case["check_files"] == {
            "projects/harness/check": "5d15da0aa44619f0a283683445cbb9c5ef016b06"
        }
        assert case["project"] == "harness" and case["bootstrap"] is False
        assert Path(case["repo"]) == SOURCE


def test_replay_frozen_check_blob_is_the_start_commits_file():
    for name in ("ticket-8", "ticket-9"):
        case = bench.load_case(dict(bench.committed_cases())[name], SOURCE)
        got = subprocess.run(
            [
                "git",
                "-C",
                str(SOURCE),
                "rev-parse",
                f"{case['start_commit']}:projects/harness/check",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if got.returncode:
            pytest.skip("the start commit is not in this checkout")
        assert got.stdout.strip() == case["check_files"]["projects/harness/check"]


def test_replay_three_repeats_six_lines_and_report(bench_case, tmp_path, capsys):
    cases = fake_cases(bench_case, tmp_path)
    code = replay_main(
        tmp_path,
        cases,
        standin(tmp_path, GOOD),
        run_agent=agent(PASS_ANSWER),
        step_env=KEY_ENV,
        version_fn=lambda: "2.1.319",
    )
    assert code == 0
    rows = [
        json.loads(l)
        for l in (tmp_path / "o" / "ledger.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 6
    assert [r["issue"] for r in rows] == [8, 8, 8, 9, 9, 9]
    assert [r["repeat"] for r in rows] == [1, 2, 3, 1, 2, 3]
    assert {r["setup_id"] for r in rows} == {"claude-code-sonnet"}
    lines = capsys.readouterr().out.splitlines()
    assert "not comparable" in lines[0] and "newer checkout" in lines[0]
    text = "\n".join(lines)
    for step in (
        "ANTHROPIC_API_KEY",
        "monthly limit",
        "2.1.319",
        "cannot read a newer checkout",
    ):
        assert step in text
    assert (
        "ticket-8: passed 3 of 3, unstable no, cost min $0.75 median $0.75 max $0.75"
        in text
    )
    assert "ticket-9: passed 3 of 3" in text


def test_replay_report_unstable_and_cost_statistics():
    def row(outcome, check, review, build, rev):
        return {
            "outcome": outcome,
            "check": check,
            "review": review,
            "build_cost_usd": build,
            "review_cost_usd": rev,
        }

    stable = [
        row("pass", "pass", "PASS", 1.0, 0.5),
        row("pass", "pass", "PASS", 3.0, 0.5),
        row("pass", "pass", "PASS", 2.0, 0.5),
    ]
    by_check = [
        row("pass", "pass", "PASS", 1, 0),
        row("fail", "fail", "PASS", 2, 0),
        row("pass", "pass", "PASS", 3, 0),
    ]
    by_review = [
        row("pass", "pass", "PASS", 1, 0),
        row("fail", "pass", "BLOCKED", 1, 0),
        row("fail", "pass", "BLOCKED", 1, 0),
    ]
    text = bench.report("s", [("a", stable), ("b", by_check), ("c", by_review)])
    assert (
        "a: passed 3 of 3, unstable no, cost min $1.50 median $2.50 max $3.50" in text
    )
    assert (
        "b: passed 2 of 3, unstable yes, cost min $1.00 median $2.00 max $3.00" in text
    )
    assert "c: passed 1 of 3, unstable yes" in text
    assert "rank" not in text.lower()


def test_replay_missing_key_refuses_before_clone(
    bench_case, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(bench, "scratch_clone", lambda *a: pytest.fail("cloned"))
    cases = fake_cases(bench_case, tmp_path)
    code = replay_main(
        tmp_path,
        cases,
        "true",
        step_env={"PATH": "/usr/bin"},
        version_fn=lambda: "2.1.319",
    )
    assert code != 0 and "ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_replay_wrong_version_refuses_with_install_line(
    bench_case, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(bench, "scratch_clone", lambda *a: pytest.fail("cloned"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("ran a command"))
    cases = fake_cases(bench_case, tmp_path)
    for found in ("2.1.320", None):
        code = replay_main(
            tmp_path,
            cases,
            "true",
            step_env=KEY_ENV,
            version_fn=lambda found=found: found,
        )
        err = capsys.readouterr().err
        assert code != 0 and "npm install -g @anthropic-ai/claude-code@2.1.319" in err
    assert not (tmp_path / "o").exists()


def test_replay_baseline_arguments_match_the_factory_command():
    args = bench.baseline_arguments(2.0)
    assert args == claude.command("sonnet", 2.0, None, ticket.DENIED_TOOLS, True)
    assert "--bare" not in args
    for flag in (
        "-p",
        "--verbose",
        "--setting-sources",
        "--disallowedTools",
        "--permission-mode",
    ):
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


def test_replay_cap_of_five_reservations_writes_five_lines(
    bench_case, tmp_path, capsys
):
    cases = fake_cases(bench_case, tmp_path)
    spend = standin(
        tmp_path, "pathlib.Path('done.txt').write_text('x')\n" + WRITE_RESULT % "2.0"
    )
    code = replay_main(
        tmp_path,
        cases,
        spend,
        "--monthly-cap-usd",
        "15",
        run_agent=lambda prompt, **_: claude.Result(True, PASS_ANSWER, "success", 1.0),
        step_env=KEY_ENV,
        version_fn=lambda: "2.1.319",
    )
    assert code != 0
    lines = (tmp_path / "o" / "ledger.jsonl").read_text().splitlines()
    assert len(lines) == 5
    assert [json.loads(l)["repeat"] for l in lines] == [1, 2, 3, 1, 2]
    assert "ticket-9: passed 2 of 3" in capsys.readouterr().out


def test_replay_gives_the_harness_only_the_bench_key(bench_case, tmp_path):
    seen = tmp_path / "seen.json"
    script = (
        f"pathlib.Path({str(seen)!r}).write_text(json.dumps("
        "{k: os.environ.get(k) for k in ('ANTHROPIC_API_KEY','GH_TOKEN')}))\n"
    ) + GOOD
    cases = fake_cases(bench_case, tmp_path)
    env = dict(KEY_ENV, GH_TOKEN="ghtoken-value")
    replay_main(
        tmp_path,
        cases,
        standin(tmp_path, script),
        run_agent=agent(PASS_ANSWER),
        step_env=env,
        version_fn=lambda: "2.1.319",
    )
    assert json.loads(seen.read_text()) == {
        "ANTHROPIC_API_KEY": "sk-test-key-value",
        "GH_TOKEN": None,
    }
    assert "sk-test-key-value" not in "".join(
        p.read_text(errors="replace")
        for p in (tmp_path / "o").rglob("*")
        if p.is_file()
    )


def test_baseline_standin_names_a_ticket_file_that_exists_when_claude_starts(
    tmp_path, monkeypatch
):
    ticket_file = tmp_path / "ticket.md"
    ticket_file.write_text("# Make done.txt\n")
    result_file = tmp_path / "result.json"
    step_env = {
        "BENCH_TICKET": str(ticket_file),
        "BENCH_BUDGET": "2.0",
        "BENCH_MODEL": "sonnet",
        "BENCH_RESULT": str(result_file),
        bench.KEY_VAR: "test-key",
    }
    calls = []

    def fake_run(cmd, input, stdout, **_):
        named = re.findall(r"[^\s`'\"]*ticket\.md", input)
        calls.append({path: Path(path).is_file() for path in named})
        stdout.write(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "built",
                    "total_cost_usd": 0.5,
                    "num_turns": 3,
                    "duration_ms": 10,
                    "usage": {"input_tokens": 1},
                }
            )
            + "\n"
        )
        return subprocess.CompletedProcess(cmd, 0, stdout=None, stderr="")

    monkeypatch.setattr(bench.subprocess, "run", fake_run)
    code = bench.baseline_standin(step_env)
    assert len(calls) == 1
    assert calls[0], "the prompt names no ticket.md"
    assert all(calls[0].values()), calls[0]
    assert code == 0
    assert json.loads(result_file.read_text())["ok"] is True


# ---- planted-defect cases --------------------------------------------------


def make_patch(bench_case, tmp_path, name, files):
    """A unified diff of `files` ({path: text}) against the fixture repo's start commit."""
    work = tmp_path / f"work-{name}"
    git("clone", "-q", bench_case["repo"], str(work), cwd=tmp_path)
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text)
    git("add", "-A", cwd=work)
    patch = tmp_path / f"{name}.patch"
    patch.write_text(git("diff", "--cached", "--no-color", cwd=work) + "\n")
    return patch


PLANTED_FILES = {"done.txt": "x", "planted.py": "a\nb\nsecret = 1\n"}
TWIN_FILES = {"done.txt": "x"}


def answer_of(*findings, standards=()):
    return json.dumps(
        {
            "spec_summary": "s",
            "standards_summary": "t",
            "spec_findings": [
                {"kind": k, "description": d, "resolution": "r", "file_path": f}
                for k, f, d in findings
            ],
            "standards_findings": [
                {"kind": k, "description": d, "resolution": "r", "file_path": f}
                for k, f, d in standards
            ],
        }
    )


NAMES_PLANTED = answer_of(("implemented_wrongly", "planted.py:3", "leaks a secret"))
NAMES_OTHER = answer_of(("implemented_wrongly", "other.py:1", "wrong"))


def planted_case(bench_case, patch, **extra):
    return dict(
        bench_case,
        patch=str(patch),
        expect="BLOCKED",
        planted_files=["planted.py"],
        stated_sentences=["Make done.txt"],
        **extra,
    )


def patch_run(case, tmp_path, answer=PASS_ANSWER, calls=None, limits=None, out=None):
    setup = {
        "setup_id": "s1",
        "harness_command": None,
        "model": "sonnet",
        "review_model": "sonnet",
        "repeat": 1,
    }
    return bench.bench_run(
        case,
        setup,
        out or tmp_path / "out",
        limits or bench.Limits(),
        agent(answer, calls),
        SOURCE,
        step_env={},
    )


@pytest.fixture
def planted(bench_case, tmp_path):
    return planted_case(
        bench_case, make_patch(bench_case, tmp_path, "p", PLANTED_FILES)
    )


def test_planted_blocked_naming_the_file_passes(planted, tmp_path):
    row = patch_run(planted, tmp_path, NAMES_PLANTED)
    assert row["outcome"] == "pass" and row["check"] == "pass"
    assert row["review"] == "BLOCKED" and row["expect"] == "BLOCKED"
    assert row["planted_named"] is True and row["patch"] == "p.patch"
    assert row["build_cost_usd"] == 0 and row["budget"] == 0
    assert row["turns"] is None and row["review_cost_usd"] == 0.25


def test_planted_review_pass_fails(planted, tmp_path):
    row = patch_run(planted, tmp_path, PASS_ANSWER)
    assert row["outcome"] == "fail" and row["review"] == "PASS"
    assert row["planted_named"] is False


def test_planted_blocked_on_another_file_fails(planted, tmp_path):
    row = patch_run(planted, tmp_path, NAMES_OTHER)
    assert row["outcome"] == "fail" and row["review"] == "BLOCKED"
    assert row["planted_named"] is False


def test_planted_only_blocking_findings_count(planted, tmp_path):
    answer = answer_of(
        ("implemented_wrongly", "other.py:1", "wrong"),
        ("scope_creep", "planted.py:3", "extra"),
        standards=[("repo_standard", "planted.py:1", "style")],
    )
    row = patch_run(planted, tmp_path, answer)
    assert row["outcome"] == "fail" and row["planted_named"] is False


def test_planted_name_in_description_counts(planted, tmp_path):
    answer = answer_of(("implemented_wrongly", None, "planted.py hard-codes a secret"))
    assert patch_run(planted, tmp_path, answer)["outcome"] == "pass"


def test_planted_red_check_skips_review(bench_case, tmp_path):
    patch = make_patch(bench_case, tmp_path, "red", {"planted.py": "x = 1\n"})
    calls = []
    row = patch_run(planted_case(bench_case, patch), tmp_path, NAMES_PLANTED, calls)
    assert row["outcome"] == "fail" and row["check"] == "fail"
    assert row["review"] is None and row["review_cost_usd"] == 0 and calls == []
    assert row["planted_named"] is None


def test_planted_patch_that_does_not_apply(bench_case, tmp_path):
    bad = tmp_path / "bad.patch"
    bad.write_text("not a diff at all\n")
    calls = []
    row = patch_run(planted_case(bench_case, bad), tmp_path, NAMES_PLANTED, calls)
    assert row["outcome"] == "fail" and row["check"] == "skipped"
    assert row["review"] is None and calls == []
    assert list((tmp_path / "out" / "runs").glob("*/patch.log"))


def test_planted_patch_editing_the_check_is_tampered(bench_case, tmp_path):
    patch = make_patch(
        bench_case, tmp_path, "evil", {"check.py": "import sys\nsys.exit(0)\n"}
    )
    calls = []
    row = patch_run(planted_case(bench_case, patch), tmp_path, NAMES_PLANTED, calls)
    assert row["check"] == "tampered" and row["outcome"] == "fail" and calls == []


def test_twin_passes_on_review_pass_and_fails_on_blocked(bench_case, tmp_path):
    twin = dict(
        bench_case, patch=str(make_patch(bench_case, tmp_path, "t", TWIN_FILES))
    )
    row = patch_run(twin, tmp_path, PASS_ANSWER)
    assert row["outcome"] == "pass" and row["expect"] == "PASS"
    assert row["planted_named"] is None and row["patch"] == "t.patch"
    blocked = patch_run(twin, tmp_path, NAMES_PLANTED, out=tmp_path / "out2")
    assert blocked["outcome"] == "fail" and blocked["planted_named"] is None


def test_patch_case_reserves_the_review_cap_only(bench_case, planted, tmp_path):
    limits = bench.Limits(monthly_cap_usd=1.0)
    assert (
        patch_run(planted, tmp_path, NAMES_PLANTED, limits=limits)["outcome"] == "pass"
    )
    with pytest.raises(bench.LedgerRefused):
        run(
            bench_case,
            tmp_path,
            standin(tmp_path, GOOD),
            limits=limits,
            out=tmp_path / "o2",
        )


def test_validate_case_rejects_bad_shapes(bench_case, planted):
    bench.validate_case(bench_case)
    bench.validate_case(planted)
    bench.validate_case(dict(bench_case, patch="x.patch"))
    bad = [
        dict(planted, expect="MAYBE"),
        {k: v for k, v in planted.items() if k != "patch"},
        {k: v for k, v in planted.items() if k != "planted_files"},
        dict(planted, planted_files=[]),
        dict(planted, planted_files="planted.py"),
        dict(planted, planted_files=[3]),
        {k: v for k, v in planted.items() if k != "stated_sentences"},
        dict(planted, stated_sentences=[]),
        dict(planted, stated_sentences=["not in the ticket"]),
        dict(bench_case, patch="x.patch", planted_files=["a.py"]),
        dict(bench_case, patch="x.patch", expect="PASS", stated_sentences=["Make"]),
    ]
    for case in bad:
        with pytest.raises(bench.BadCase):
            bench.validate_case(case)


def write_planted_dir(bench_case, tmp_path, numbers=(8,), twin_numbers=None):
    """A cases directory of planted cases and twins on the fixture repo."""
    d = tmp_path / "pcases"
    d.mkdir()
    (d / "ticket.md").write_text("# Make done.txt\n")
    twins = numbers if twin_numbers is None else twin_numbers
    for n in numbers:
        patch = make_patch(bench_case, tmp_path, f"pl{n}", PLANTED_FILES)
        (d / f"planted-{n}.patch").write_text(patch.read_text())
        case = dict(
            bench_case,
            ticket="ticket.md",
            patch=f"planted-{n}.patch",
            expect="BLOCKED",
            planted_files=["planted.py"],
            stated_sentences=["Make done.txt"],
        )
        (d / f"planted-{n}.json").write_text(json.dumps(case))
    for n in twins:
        patch = make_patch(bench_case, tmp_path, f"tw{n}", TWIN_FILES)
        (d / f"planted-{n}-twin.patch").write_text(patch.read_text())
        case = dict(
            bench_case, ticket="ticket.md", patch=f"planted-{n}-twin.patch", issue=n
        )
        (d / f"planted-{n}-twin.json").write_text(json.dumps(case))
    return d


def test_planted_cases_order_and_pairing(bench_case, tmp_path):
    d = write_planted_dir(bench_case, tmp_path, numbers=(8, 18, 9))
    assert [n for n, _ in bench.planted_cases(d)] == [
        "planted-8",
        "planted-8-twin",
        "planted-9",
        "planted-9-twin",
        "planted-18",
        "planted-18-twin",
    ]
    assert bench.committed_cases(d) == []


def test_planted_cases_need_a_twin_and_a_case(bench_case, tmp_path):
    d = write_planted_dir(bench_case, tmp_path, numbers=(8,), twin_numbers=())
    with pytest.raises(bench.BadCase):
        bench.planted_cases(d)
    (tmp_path / "pcases2").mkdir()
    orphan = write_planted_dir(
        bench_case, tmp_path / "pcases2", numbers=(), twin_numbers=(8,)
    )
    with pytest.raises(bench.BadCase):
        bench.planted_cases(orphan)


def clone_reviewer(blocked_answer):
    """A Review stand-in: BLOCKED when the clone holds planted.py, else PASS."""

    def run(prompt, **kw):
        planted_here = (Path(kw["cwd"]) / "planted.py").exists()
        text = blocked_answer if planted_here else PASS_ANSWER
        return claude.Result(True, text, "success", 0.25)

    return run


def planted_replay(tmp_path, cases, *extra, **kw):
    return bench.main(
        ["--replay-planted", "--out", str(tmp_path / "o"), *extra],
        cases_dir=cases,
        **kw,
    )


def test_replay_planted_holds_with_its_twin(bench_case, tmp_path, capsys):
    d = write_planted_dir(bench_case, tmp_path)
    code = planted_replay(
        tmp_path,
        d,
        run_agent=clone_reviewer(NAMES_PLANTED),
        step_env=KEY_ENV,
        version_fn=lambda: "2.1.319",
    )
    assert code == 0
    rows = [
        json.loads(l)
        for l in (tmp_path / "o" / "ledger.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 6
    out = capsys.readouterr().out
    assert "planted-8: passed 3 of 3" in out
    assert "; Review BLOCKED in 3 of 3 runs, named a planted file in 3" in out
    assert "planted-8-twin: passed 3 of 3" in out
    assert "planted-8 with its twin: holds" in out


def test_replay_planted_twin_blocked_does_not_hold(bench_case, tmp_path, capsys):
    d = write_planted_dir(bench_case, tmp_path)
    code = planted_replay(
        tmp_path,
        d,
        run_agent=agent(NAMES_PLANTED),
        step_env=KEY_ENV,
        version_fn=lambda: "2.1.319",
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "planted-8-twin: passed 0 of 3" in out
    assert "planted-8 with its twin: does not hold" in out


def test_replay_planted_missing_key_refuses_before_clone(
    bench_case, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(bench, "scratch_clone", lambda *a: pytest.fail("cloned"))
    d = write_planted_dir(bench_case, tmp_path)
    code = planted_replay(
        tmp_path, d, step_env={"PATH": "/usr/bin"}, version_fn=lambda: "2.1.319"
    )
    assert code != 0 and "ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_replay_planted_bad_case_exits_2_before_clone(
    bench_case, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(bench, "scratch_clone", lambda *a: pytest.fail("cloned"))
    d = write_planted_dir(bench_case, tmp_path, twin_numbers=())
    code = planted_replay(tmp_path, d, step_env=KEY_ENV, version_fn=lambda: "2.1.319")
    assert code == 2 and "bench: bad case:" in capsys.readouterr().err


def check_planted_main(tmp_path, d):
    return bench.main(
        ["--check-planted", "--out", str(tmp_path / "o")],
        run_agent=lambda *a, **k: pytest.fail("called Review"),
        step_env={},
        cases_dir=d,
    )


def test_check_planted_green(bench_case, tmp_path, capsys):
    d = write_planted_dir(bench_case, tmp_path)
    assert check_planted_main(tmp_path, d) == 0
    out = capsys.readouterr().out
    assert "planted-8: patch applied, check pass" in out
    assert "planted-8-twin: patch applied, check pass" in out
    assert not (tmp_path / "o").exists()


def test_check_planted_red_patch(bench_case, tmp_path, capsys):
    d = write_planted_dir(bench_case, tmp_path)
    (d / "planted-8.patch").write_text(
        make_patch(bench_case, tmp_path, "r", {"planted.py": "x\n"}).read_text()
    )
    assert check_planted_main(tmp_path, d) == 1
    assert "planted-8: patch applied, check fail" in capsys.readouterr().out


def test_check_planted_patch_that_does_not_apply(bench_case, tmp_path, capsys):
    d = write_planted_dir(bench_case, tmp_path)
    (d / "planted-8-twin.patch").write_text("garbage\n")
    assert check_planted_main(tmp_path, d) == 1
    assert "planted-8-twin: patch does not apply" in capsys.readouterr().out


def tracer_argv(tmp_path, case_file, *extra):
    return [
        "--case",
        str(case_file),
        "--setup-id",
        "s",
        "--out",
        str(tmp_path / "o"),
        *extra,
    ]


def test_tracer_planted_case_needs_no_harness_command(planted, tmp_path):
    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps(planted))
    code = bench.main(tracer_argv(tmp_path, case_file), run_agent=agent(NAMES_PLANTED))
    assert code == 0
    lines = (tmp_path / "o" / "ledger.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["outcome"] == "pass"


def test_tracer_case_without_patch_still_needs_harness_command(bench_case, tmp_path):
    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps(bench_case))
    with pytest.raises(SystemExit):
        bench.main(tracer_argv(tmp_path, case_file), run_agent=agent(PASS_ANSWER))


def test_tracer_bad_case_exits_2_and_writes_nothing(planted, tmp_path, capsys):
    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps(dict(planted, planted_files=[])))
    code = bench.main(tracer_argv(tmp_path, case_file), run_agent=agent(PASS_ANSWER))
    assert code == 2 and "bench: bad case:" in capsys.readouterr().err
    assert not (tmp_path / "o" / "ledger.jsonl").exists()


def test_report_planted_lines_and_old_rows():
    def row(outcome, review, named):
        return {
            "outcome": outcome,
            "check": "pass",
            "review": review,
            "build_cost_usd": 0,
            "review_cost_usd": 0.25,
            "expect": "BLOCKED",
            "planted_named": named,
        }

    old = {
        "outcome": "pass",
        "check": "pass",
        "review": "PASS",
        "build_cost_usd": 1,
        "review_cost_usd": 0,
    }
    twin = dict(old, expect="PASS", planted_named=None)
    text = bench.report(
        "s",
        [
            (
                "planted-8",
                [row("pass", "BLOCKED", True)] * 2 + [row("fail", "PASS", False)],
            ),
            ("planted-8-twin", [twin] * 3),
            ("ticket-8", [old] * 3),
        ],
    )
    assert "; Review BLOCKED in 2 of 3 runs, named a planted file in 2" in text
    assert "planted-8 with its twin: does not hold" in text
    assert (
        "ticket-8: passed 3 of 3, unstable no, cost min $1.00 median $1.00 max $1.00"
        in text
    )
    assert "ticket-8 with its twin" not in text


def test_load_planted_guards(bench_case, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bench, "scratch_clone", lambda *a: pytest.fail("cloned"))
    d = write_planted_dir(bench_case, tmp_path)
    assert [n for n, _ in bench.load_planted(d, SOURCE)][:2] == [
        "planted-8",
        "planted-8-twin",
    ]
    twin = json.loads((d / "planted-8-twin.json").read_text())
    (d / "planted-8-twin.json").write_text(
        json.dumps({k: v for k, v in twin.items() if k != "patch"})
    )
    code = planted_replay(tmp_path, d, step_env=KEY_ENV, version_fn=lambda: "2.1.319")
    assert code == 2 and "bench: bad case:" in capsys.readouterr().err
    assert check_planted_main(tmp_path, d) == 2
    assert not (tmp_path / "o").exists()


def test_load_planted_twin_with_another_start_commit(bench_case, tmp_path):
    d = write_planted_dir(bench_case, tmp_path)
    twin = json.loads((d / "planted-8-twin.json").read_text())
    twin["start_commit"] = "0" * 40
    (d / "planted-8-twin.json").write_text(json.dumps(twin))
    with pytest.raises(bench.BadCase, match="start_commit"):
        bench.load_planted(d, SOURCE)


def test_load_planted_case_that_expects_pass(bench_case, tmp_path):
    d = write_planted_dir(bench_case, tmp_path)
    case = json.loads((d / "planted-8.json").read_text())
    for k in ("expect", "planted_files", "stated_sentences"):
        del case[k]
    (d / "planted-8.json").write_text(json.dumps(case))
    with pytest.raises(bench.BadCase, match="planted-8"):
        bench.load_planted(d, SOURCE)


CHECK_8 = {"projects/harness/check": "5d15da0aa44619f0a283683445cbb9c5ef016b06"}
PLANTED_TABLE = {
    8: (
        TICKET_8,
        "harness",
        "projects/harness/check",
        CHECK_8,
        [
            "projects/harness/src/harness_lab/tools.py",
            "projects/harness/tests/test_tools.py",
        ],
    ),
    9: (
        TICKET_9,
        "harness",
        "projects/harness/check",
        CHECK_8,
        ["projects/harness/src/harness_lab/cli.py"],
    ),
    18: (
        (
            "089fdbcec4f4e3d4c59342d7c930fe43be3cf8a0",
            "8b857f6ff49100fbead06eda0a7bd4416c9144eed338295980a76c5dd33847d9",
        ),
        None,
        "uv run --locked pytest tests/factory",
        {"pyproject.toml": "1ad9e8663de29cfae34ff4d2686ffc24b11f1e67"},
        ["factory/ticket.py"],
    ),
}


def test_committed_planted_cases_match_the_record():
    assert [n for n, _ in bench.planted_cases()] == [
        "planted-8",
        "planted-8-twin",
        "planted-9",
        "planted-9-twin",
        "planted-18",
        "planted-18-twin",
    ]
    assert [n for n, _ in bench.committed_cases()] == ["ticket-8", "ticket-9"]
    loaded = dict(bench.load_planted(bench.CASES_DIR, SOURCE))
    for n, (rec, project, command, files, planted_files) in PLANTED_TABLE.items():
        start, digest = rec
        case, twin = loaded[f"planted-{n}"], loaded[f"planted-{n}-twin"]
        assert case["start_commit"] == start and case["issue"] == n
        assert case["project"] == project and case["check_command"] == command
        assert case["check_files"] == files and case["expect"] == "BLOCKED"
        assert case["planted_files"] == planted_files and case["stated_sentences"]
        ticket_path = Path(case["ticket"])
        assert ticket_path == SOURCE / "factory" / "bench_cases" / f"ticket-{n}.md"
        assert hashlib.sha256(ticket_path.read_bytes()).hexdigest() == digest
        assert Path(case["patch"]).is_file()
        assert Path(case["patch"]).name == f"planted-{n}.patch"
        assert twin["expect"] == "PASS" and "planted_files" not in twin
        assert Path(twin["patch"]).name == f"planted-{n}-twin.patch"
        assert Path(twin["patch"]).is_file()
        assert twin["start_commit"] == start


def patch_sections(path):
    """{file path: its diff text without index lines} for a unified diff."""
    sections, current = {}, None
    for line in Path(path).read_text().splitlines():
        m = re.match(r"diff --git a/(\S+) b/\S+$", line)
        if m:
            current = sections.setdefault(m.group(1), [])
        if current is not None and not line.startswith("index "):
            current.append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def test_committed_planted_patch_differs_from_its_twin_in_every_planted_file():
    loaded = dict(bench.load_planted(bench.CASES_DIR, SOURCE))
    for n in PLANTED_TABLE:
        case, twin = loaded[f"planted-{n}"], loaded[f"planted-{n}-twin"]
        a, b = patch_sections(case["patch"]), patch_sections(twin["patch"])
        differ = {k for k in a.keys() | b.keys() if a.get(k) != b.get(k)}
        assert differ and set(case["planted_files"]) <= differ
        for sections in (a, b):
            assert not set(sections) & set(case["check_files"])


def test_committed_planted_patches_apply_at_their_start_commits(tmp_path):
    for name, case in bench.load_planted(bench.CASES_DIR, SOURCE):
        start = case["start_commit"]
        have = subprocess.run(
            ["git", "-C", str(SOURCE), "cat-file", "-e", f"{start}^{{commit}}"],
            capture_output=True,
            check=False,
        )
        if have.returncode:
            pytest.skip("the start commit is not in this checkout")
        env = dict(os.environ, GIT_INDEX_FILE=str(tmp_path / f"index-{name}"))
        for cmd in (
            ["read-tree", start],
            ["apply", "--cached", "--check", case["patch"]],
        ):
            p = subprocess.run(
                ["git", "-C", str(SOURCE), *cmd],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            assert p.returncode == 0, f"{name}: git {cmd[0]}: {p.stderr}"
        for rel, blob in case["check_files"].items():
            got = git("rev-parse", f"{start}:{rel}", cwd=SOURCE)
            assert got == blob
