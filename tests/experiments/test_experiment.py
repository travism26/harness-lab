import ast
import io
import os
import re
import shutil
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest

from experiments import experiment
from experiments.experiment import (
    Check,
    credential_reasons,
    main,
    read_ceilings,
    run_checks,
    scrubbed_env,
    validate_text,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
README = REPO / "experiments" / "README.md"
TEMPLATE = REPO / "experiments" / "_template"
EXAMPLE = REPO / "experiments" / "example-budget-cap" / "request.md"
VALID = (FIXTURES / "valid.md").read_text()


def _errors(text, readme=README):
    request, errors = validate_text(text, Path("request.md"), readme)
    assert (request is None) == bool(errors)
    return errors


def _validate_cli(path, capsys):
    code = main(["validate", str(path)])
    return code, capsys.readouterr()


def _readme(tmp_path, cost="0.10", box="3"):
    path = tmp_path / "README.md"
    path.write_text(
        f"| Ceiling | Value |\n|---|---|\n| Cost cap (USD) | {cost} |\n| Timebox (minutes) | {box} |\n"
    )
    return path


def _quiet(checks, cwd, timebox_s=60, **kw):
    return run_checks(checks, cwd, timebox_s, log=io.StringIO(), **kw)


def _check(command, name="c"):
    return Check(name, command, "it passes")


# --- check 1: format ---------------------------------------------------------------


def test_example_request_and_valid_fixture_are_accepted(capsys):
    for path in (EXAMPLE, FIXTURES / "valid.md"):
        code, out = _validate_cli(path, capsys)
        assert code == 0
        assert out.out == f"ok: {path}\n"


def test_template_is_rejected_until_filled():
    raw = (TEMPLATE / "request.md").read_text()
    assert any("{{title}}" in e for e in _errors(raw))
    values = {
        "title": "stand-in",
        "hypothesis": "A stand-in claim.",
        "source-url": "https://example.com/notes",
        "check-name": "A check",
        "check-command": "true",
        "pass-means": "it exits 0.",
        "cost-cap": "0.50",
        "timebox": "5",
        "login": "subscription",
        "slug": "stand-in",
    }
    filled = re.sub(r"\{\{([a-z][a-z0-9-]*)\}\}", lambda m: values[m.group(1)], raw)
    assert "{{" not in filled
    assert _errors(filled) == []


@pytest.mark.parametrize(
    "name, expected",
    [
        ("missing-hypothesis", "Hypothesis"),
        ("no-https-source", "https://"),
        ("zero-checks", "no '### ' check"),
        ("missing-cost-cap", "Cost cap (USD)"),
        ("missing-timebox", "Timebox (minutes)"),
        ("missing-login", "Model / login"),
        ("missing-revert", "Revert"),
        ("six-checks", "6 checks"),
    ],
)
def test_invalid_fixtures_are_named(name, expected, capsys):
    code, out = _validate_cli(FIXTURES / f"{name}.md", capsys)
    assert code == 1
    assert expected in out.err
    assert out.out == ""
    assert re.search(r"invalid: .*\(\d+ errors?\)", out.err)


def test_heading_inside_a_command_is_not_a_check():
    text = VALID.replace("true\n```", "true\n### a comment, not a check\n```", 1)
    request, errors = validate_text(text, Path("request.md"), README)
    assert errors == []
    assert len(request.checks) == 2
    assert request.checks[0].command == "true\n### a comment, not a check"


def test_five_checks_are_accepted():
    checks = "\n".join(
        f"### {i}. C\n\n```sh\ntrue\n```\n\nPass means: ok.\n" for i in range(1, 6)
    )
    text = re.sub(r"### 1\..*?(?=## Cost)", checks + "\n", VALID, flags=re.DOTALL)
    assert _errors(text) == []


def test_all_errors_are_collected():
    text = VALID.replace("## Revert", "## Extra").replace("0.25", "x")
    assert len(_errors(text)) >= 3


def test_duplicate_heading():
    errors = _errors(VALID + "\n## Revert\n\nAgain.\n")
    assert any("more than once" in e and "Revert" in e for e in errors)


def test_unknown_heading():
    assert any("unknown heading" in e for e in _errors(VALID + "\n## Notes\n\nx\n"))


def test_empty_section():
    text = VALID.replace("## Revert\n\nDelete the synthetic branch.", "## Revert\n\n")
    assert any("Revert" in e and "empty" in e for e in _errors(text))


def test_two_code_blocks_in_a_check():
    text = VALID.replace("```sh\ntrue\n```\n", "```sh\ntrue\n```\n\n```sh\ntrue\n```\n")
    assert any("exactly one code block" in e for e in _errors(text))


def test_empty_command():
    text = VALID.replace("```sh\ntrue\n```", "```sh\n\n```")
    assert any("empty command" in e for e in _errors(text))


def test_check_without_pass_means():
    text = VALID.replace("Pass means: the command exits 0.", "It should work.")
    assert any("Pass means" in e for e in _errors(text))


def test_pass_means_joins_following_lines():
    text = VALID.replace(
        "Pass means: the command exits 0.", "Pass means: the command\nexits 0."
    )
    request, errors = validate_text(text, Path("r.md"), README)
    assert errors == []
    assert request.checks[0].pass_means == "the command exits 0."


def test_heading_inside_fence_is_not_a_heading():
    text = VALID.replace("```sh\ntrue\n```", "```sh\ntrue\n## Not a heading\n```", 1)
    request, errors = validate_text(text, Path("r.md"), README)
    assert errors == []
    assert request.checks[0].command == "true\n## Not a heading"


@pytest.mark.parametrize(
    "source, expected",
    [
        ("https://user:pw@example.com/x", "userinfo"),
        ("https://localhost/x", "host"),
        ("https://intranet/x", "host"),
        ("https://127.0.0.1/x", "IP"),
        ("example.com/x", "https://"),
        ("http://example.com/x", "https://"),
    ],
)
def test_bad_public_sources(source, expected):
    text = VALID.replace("https://example.com/release-notes (synthetic source)", source)
    assert any(expected in e for e in _errors(text))


def test_bare_prose_source_line():
    text = VALID.replace("(synthetic source)\n", "(synthetic source)\nsee the docs\n")
    assert any("see the docs" in e for e in _errors(text))


@pytest.mark.parametrize("cap", ["0", "0.00", "1.234", "abc", "-1"])
def test_bad_cost_caps(cap):
    assert _errors(VALID.replace("\n0.25\n", f"\n{cap}\n"))


def test_dollar_sign_cap_is_accepted():
    assert _errors(VALID.replace("\n0.25\n", "\n$0.25\n")) == []


@pytest.mark.parametrize("box", ["0", "1.5", "five", "-3"])
def test_bad_timeboxes(box):
    assert _errors(VALID.replace("\n5\n\n## Model", f"\n{box}\n\n## Model"))


def test_bad_login():
    assert any(
        "Model / login" in e
        for e in _errors(VALID.replace("subscription", "free ride"))
    )


def test_metered_key_login_with_notes():
    text = VALID.replace("subscription", "metered key\n\nNo live call needed.")
    assert _errors(text) == []


def test_unreadable_request_file(capsys):
    code, out = _validate_cli(REPO / "no-such-request.md", capsys)
    assert code == 1
    assert "cannot read" in out.err


# --- check 2: ceilings and secrets --------------------------------------------------


def test_over_ceiling_fixtures(capsys):
    code, out = _validate_cli(FIXTURES / "cost-cap-over-ceiling.md", capsys)
    assert code == 1
    assert "1000" in out.err and "ceiling" in out.err
    code, out = _validate_cli(FIXTURES / "timebox-over-ceiling.md", capsys)
    assert code == 1
    assert "100000" in out.err and "ceiling" in out.err


def test_committed_ceilings_are_positive():
    ceilings = read_ceilings(README)
    assert ceilings.cost_cap_usd > 0
    assert ceilings.timebox_minutes > 0


def test_ceiling_boundaries_come_from_the_readme():
    ceilings = read_ceilings(README)
    cap = ceilings.cost_cap_usd
    box = ceilings.timebox_minutes
    assert _errors(VALID.replace("0.25", f"{cap}")) == []
    assert _errors(VALID.replace("0.25", f"{cap + Decimal('0.01')}"))
    assert _errors(VALID.replace("\n5\n\n## Model", f"\n{box}\n\n## Model")) == []
    assert _errors(VALID.replace("\n5\n\n## Model", f"\n{box + 1}\n\n## Model"))


def test_ceilings_are_read_from_the_given_readme(tmp_path):
    readme = _readme(tmp_path)
    errors = _errors(VALID, readme)
    assert len(errors) == 2
    assert any("0.25" in e and "0.10" in e for e in errors)
    assert any("5" in e and "3" in e for e in errors)


@pytest.mark.parametrize(
    "content",
    [
        "no table here\n",
        "| Cost cap (USD) | 2 |\n| Cost cap (USD) | 3 |\n| Timebox (minutes) | 60 |\n",
        "| Cost cap (USD) | 2 |\n| Timebox (minutes) | 60 |\n| Timebox (minutes) | 61 |\n",
        "| Cost cap (USD) | 0 |\n| Timebox (minutes) | 60 |\n",
        "| Cost cap (USD) | 2 |\n| Timebox (minutes) | 0 |\n",
        "| Cost cap (USD) | 2 |\n",
    ],
)
def test_unreadable_ceilings_fail_closed(tmp_path, content):
    readme = tmp_path / "README.md"
    readme.write_text(content)
    assert any(
        "ceilings" in e and "experiments/README.md" in e for e in _errors(VALID, readme)
    )
    assert any("ceilings" in e for e in _errors(VALID, tmp_path / "missing.md"))


REJECT = [
    "env",
    "env | grep X",
    "/usr/bin/env python3 x.py",
    "printenv HOME",
    "true && printenv",
    "ls --env-file-missing && env",
    "os.environ",
    "cat /proc/self/environ",
    "python3 -c \"import os; os.getenv('X')\"",
    "node -e 'process.env'",
    "set",
    "set | grep X",
    "true; set > out.txt",
    "(set)",
    "export -p",
    "declare -p",
    "typeset -p",
    "cat .env",
    "cat ./.env",
    "cat config/.env.local",
    "source .envrc",
    "cat ~/.claude/settings.json",
    "ls $HOME/.claude",
    "cat ~/.claude.json",
    "cat ~/.config/gh/hosts.yml",
    "cat ~/.ssh/id_rsa",
    "ls ~/.aws",
    "cat ~/.netrc",
    "cat ~/.git-credentials",
    "security find-generic-password -s x",
    "security dump-keychain",
    "gh auth token",
    "gh auth status",
    "git credential fill",
    "echo $ANTHROPIC_API_KEY",
    'curl -H "x: ${GH_TOKEN}"',
    'test -n "$my_secret"',
    "echo ${#OPENAI_API_KEY}",
    "echo ${!SOME_TOKEN}",
]
ACCEPT = [
    "true",
    "python3 -m venv build",
    "ls --env-file-missing",
    "echo environment_ok",
    "set -e; make test",
    "set -euo pipefail",
    "git config --get remote.origin.url",
    "grep -q 'set to' file.txt",
    "export LANG=C; make",
    "ls .venv",
    "grep -q security README.md",
    "gh --version",
    "git status",
    "grep -q max_tokens config.json",
    "echo keyboard",
    "echo $HOME",
    'python3 -c "max_tokens = 5"',
]


@pytest.mark.parametrize("command", REJECT)
def test_credential_reasons_reject(command):
    assert credential_reasons(command), command


@pytest.mark.parametrize("command", ACCEPT)
def test_credential_reasons_accept(command):
    assert credential_reasons(command) == [], command


def test_example_request_commands_are_accepted():
    request, errors = validate_text(EXAMPLE.read_text(), EXAMPLE, README)
    assert errors == []
    assert len(request.checks) == 4
    for check in request.checks:
        assert credential_reasons(check.command) == []


def test_credential_fixture_is_rejected(capsys):
    code, out = _validate_cli(FIXTURES / "credential-check.md", capsys)
    assert code == 1
    assert "Reads a login" in out.err


def test_token_shaped_string_is_rejected_without_echo():
    token = "gh" + "p_" + "x" * 20
    errors = _errors(VALID.replace("trivial", f"trivial {token}"))
    assert errors
    assert all(token not in e for e in errors)
    assert any("token" in e for e in errors)


def test_token_shaped_string_is_the_only_error():
    # A bad source line is normally quoted in its error; with a token in it, it is not.
    token = "gh" + "p_" + "x" * 20
    text = VALID.replace(
        "https://example.com/release-notes", f"http://example.com/{token}"
    )
    errors = _errors(text)
    assert len(errors) == 1
    assert token not in errors[0] and "token" in errors[0]


# --- check 3: runner ----------------------------------------------------------------


def test_scrubbed_env_has_exactly_three_keys(monkeypatch):
    monkeypatch.setenv("EXPERIMENT_EXTRA", "1")
    monkeypatch.setenv("PATH", "/some/bin")
    monkeypatch.setenv("LANG", "xx")
    assert scrubbed_env("/tmp/h") == {
        "PATH": "/some/bin",
        "HOME": "/tmp/h",
        "LANG": "xx",
    }
    monkeypatch.delenv("PATH")
    monkeypatch.delenv("LANG")
    env = scrubbed_env("/tmp/h")
    assert sorted(env) == ["HOME", "LANG", "PATH"]
    assert env["LANG"] == "C.UTF-8"


def test_parent_environment_does_not_reach_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPERIMENT_DUMMY_TOKEN", "dummy-value")
    cmd = 'test -z "${EXPERIMENT_DUMMY_TOKEN+x}"'
    leaked = subprocess.run(["/bin/sh", "-c", cmd])
    assert leaked.returncode != 0
    (result,) = _quiet([_check(cmd)], tmp_path)
    assert result.result == "pass"


def test_check_environment_and_home(tmp_path):
    cmd = (
        "env | sed 's/=.*//' | sort > names.txt; "
        'printf "%s" "$HOME" > home.txt; ls -A "$HOME" | wc -l > count.txt'
    )
    (result,) = _quiet([_check(cmd)], tmp_path)
    assert result.result == "pass"
    names = set((tmp_path / "names.txt").read_text().split())
    assert names - {"PWD", "SHLVL", "_", "OLDPWD"} == {"HOME", "LANG", "PATH"}
    home = Path((tmp_path / "home.txt").read_text())
    assert (tmp_path / "count.txt").read_text().strip() == "0"
    assert home != Path.home()
    assert not home.exists()


def test_check_timeout_kills_and_continues(tmp_path):
    start = time.monotonic()
    results = _quiet(
        [_check("sleep 30"), _check("true")], tmp_path, check_timeout_s=0.3
    )
    assert time.monotonic() - start < 5
    assert (results[0].result, results[0].timed_out, results[0].exit_code) == (
        "fail",
        True,
        None,
    )
    assert results[1].result == "pass"


def test_background_process_does_not_outlive_its_check(tmp_path):
    cmd = "sleep 30 >/dev/null 2>&1 & echo $! > pid.txt"
    (result,) = _quiet([_check(cmd)], tmp_path)
    assert result.result == "pass"
    pid = int((tmp_path / "pid.txt").read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    pytest.fail("the check's background process is still running")


def test_timebox_stops_the_run(tmp_path):
    checks = [_check("true"), _check("sleep 30"), _check("true")]
    start = time.monotonic()
    results = _quiet(checks, tmp_path, timebox_s=0.5)
    assert time.monotonic() - start < 5
    assert [r.result for r in results] == ["pass", "fail", "not run"]
    assert results[1].timed_out
    assert results[2].exit_code is None and results[2].duration_s is None


def test_zero_timebox_runs_nothing(tmp_path):
    log = io.StringIO()
    results = run_checks(
        [_check("touch ran.txt", "first"), _check("true")], tmp_path, 0, log=log
    )
    assert [r.result for r in results] == ["not run", "not run"]
    assert "--- first: not run" in log.getvalue()
    assert not (tmp_path / "ran.txt").exists()


def test_output_tail_goes_to_the_log_only(tmp_path):
    log = io.StringIO()
    run_checks([_check("echo hello-from-check", "named")], tmp_path, 60, log=log)
    assert "hello-from-check" in log.getvalue() and "named" in log.getvalue()


def _copy(fixture, tmp_path):
    dest = tmp_path / "req" / "request.md"
    dest.parent.mkdir(exist_ok=True)
    shutil.copy(FIXTURES / fixture, dest)
    return dest


def test_exit_codes_through_the_cli(tmp_path, capsys):
    request = _copy("failing-check.md", tmp_path)
    out = tmp_path / "out.md"
    assert main(["run", str(request), "--out", str(out)]) == 1
    rows = re.findall(
        r"^\| (\d) \| .*? \| (\d+) \| (pass|fail) \|", out.read_text(), re.MULTILINE
    )
    assert [(c, r) for _, c, r in rows] == [("0", "pass"), ("1", "fail"), ("3", "fail")]
    assert "results:" in capsys.readouterr().out

    valid = _copy("valid.md", tmp_path)
    assert main(["run", str(valid), "--out", str(tmp_path / "ok.md")]) == 0


def test_default_output_is_next_to_the_request(tmp_path):
    request = _copy("valid.md", tmp_path)
    assert main(["run", str(request)]) == 0
    assert (request.parent / "results.md").is_file()


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_results_content_in_a_git_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "exp").mkdir(parents=True)
    request = repo / "exp" / "request.md"
    text = VALID.replace("true\n```", 'echo uniq""marker\n```', 1)
    request.write_text(text)
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "init",
    )
    sha = _git(repo, "rev-parse", "HEAD")
    out = tmp_path / "out" / "results.md"
    out.parent.mkdir()
    assert main(["run", str(request), "--out", str(out)]) == 0
    body = out.read_text()
    assert f"| Commit | `{sha}` |" in body
    assert "| Uncommitted changes | no |" in body
    assert "| Request | `exp/request.md` |" in body
    assert 'echo uniq""marker' in body
    assert "uniqmarker" not in body
    assert "| Agent cost (USD) |  |" in body
    assert "| Claude Code version |  |" in body
    assert "| Cost basis | client-estimate |" in body
    assert "| Cost cap (USD) | 0.25 |" in body
    assert "Result: 2 pass, 0 fail, 0 not run." in body
    assert body.endswith("```\n\nPass means: the request folder exists.\n")

    request.write_text(text + "\n")
    assert experiment.git_facts(request.parent) == (sha, "yes")


def test_results_outside_a_repo(tmp_path):
    request = _copy("valid.md", tmp_path)
    out = tmp_path / "out.md"
    assert main(["run", str(request), "--out", str(out)]) == 0
    body = out.read_text()
    assert "| Commit | `unknown` |" in body
    assert "| Uncommitted changes | unknown |" in body
    assert f"| Request | `{request}` |" in body


def _shape(text):
    labels, headings = [], []
    in_fence = in_table = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        elif in_fence:
            continue
        elif re.match(r"#{1,2} ", line):
            headings.append(line if line.startswith("# ") else "## " + line[3:])
        elif line.startswith("|") and not headings[1:]:
            labels.append(line.split("|")[1].strip())
    return labels, headings


def test_results_follow_the_template(tmp_path):
    request = _copy("failing-check.md", tmp_path)
    out = tmp_path / "out.md"
    main(["run", str(request), "--out", str(out)])
    template = (TEMPLATE / "results.md").read_text()
    assert "| Cost basis | client-estimate |" in template
    assert "| Agent cost (USD) |  |" in template
    assert "| Claude Code version |  |" in template
    assert _shape(out.read_text()) == _shape(template)
    assert _shape(template)[0][:3] == ["Field", "---", "Request"]


def test_pipe_in_check_name_is_escaped_and_numbering_stripped(tmp_path):
    request = tmp_path / "request.md"
    request.write_text(VALID.replace("### 1. True succeeds", "### 1. A | B"))
    out = tmp_path / "out.md"
    assert main(["run", str(request), "--out", str(out)]) == 0
    body = out.read_text()
    assert "| 1 | A \\| B | 0 | pass |" in body
    assert "### 1. A | B" in body


def test_invalid_request_runs_nothing(tmp_path, capsys):
    request = tmp_path / "request.md"
    shutil.copy(FIXTURES / "credential-check.md", request)
    out = tmp_path / "out.md"
    assert main(["run", str(request), "--out", str(out)]) == 2
    assert not out.exists()
    assert not (tmp_path / "results.md").exists()
    assert "error:" in capsys.readouterr().err


def test_elapsed_minutes_beyond_the_timebox(tmp_path):
    request = _copy("valid.md", tmp_path)
    out = tmp_path / "out.md"
    assert (
        main(["run", str(request), "--out", str(out), "--elapsed-minutes", "10"]) == 1
    )
    assert "Result: 0 pass, 0 fail, 2 not run." in out.read_text()


def test_slow_fixture_hits_the_timebox(tmp_path):
    request = _copy("slow-check.md", tmp_path)
    out = tmp_path / "out.md"
    start = time.monotonic()
    code = main(["run", str(request), "--out", str(out), "--elapsed-minutes", "0.99"])
    assert time.monotonic() - start < 5
    assert code == 1
    assert "| 2 | Slow | timeout | fail |" in out.read_text()
    assert "Result: 1 pass, 1 fail, 1 not run." in out.read_text()


@pytest.mark.parametrize(
    "flags",
    [["--check-timeout", "0"], ["--check-timeout", "-1"], ["--elapsed-minutes", "-1"]],
)
def test_bad_run_flags(flags, tmp_path):
    request = _copy("valid.md", tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["run", str(request), *flags])
    assert exc.value.code == 2


# --- check 4: stdlib only -----------------------------------------------------------


def test_experiment_imports_only_the_standard_library():
    tree = ast.parse((REPO / "experiments" / "experiment.py").read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            modules.add(node.module.split(".")[0])
    assert modules
    assert modules <= set(sys.stdlib_module_names)
