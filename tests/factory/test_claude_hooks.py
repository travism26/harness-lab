"""Checks the `.claude/hooks/block_secret.py` PreToolUse hook and its settings entry."""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".claude" / "hooks"
HOOK = HOOKS / "block_secret.py"
STOP = HOOKS / "stop_check.py"
RECORD = HOOKS / "record_check.py"
SETTINGS = ROOT / ".claude" / "settings.json"

API_KEY = "sk-ant-" + "api03-" + "FIXTUREONLY"
BEARER = "Bearer" + " " + "FIXTURE-ONLY-" + "x" * 20
PEM_HEADER = "-" * 5 + "BEGIN FAKE " + "PRIVATE" + " KEY" + "-" * 5
PEM = (
    PEM_HEADER
    + "\nFIXTUREONLYFILLER\n"
    + "-" * 5
    + "END FAKE "
    + "PRIVATE"
    + " KEY"
    + "-" * 5
    + "\n"
)

GIT_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")} | {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}


def run_hook(command, cwd, tool_name="Bash"):
    payload = {
        "session_id": "fixture-session",
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {"command": command},
    }
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=GIT_ENV,
        check=False,
    )


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, env=GIT_ENV, check=True, capture_output=True
    )


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    return tmp_path


def deny_reason(result):
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert output["permissionDecision"] == "deny"
    return output["permissionDecisionReason"]


def assert_allowed(result):
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def stage(repo, name, text):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(repo, "add", name)


@pytest.mark.parametrize(
    ("fixture", "kind"),
    [(API_KEY, "api-key"), (BEARER, "bearer"), (PEM_HEADER, "pem")],
)
def test_secret_in_command_text_is_denied(tmp_path, fixture, kind):
    result = run_hook("curl -H 'x: " + fixture + "' https://example.invalid", tmp_path)
    assert deny_reason(result) == f"blocked: {kind} in command"
    assert fixture not in result.stdout + result.stderr


def test_powershell_tool_is_scanned_too(tmp_path):
    result = run_hook("echo " + API_KEY, tmp_path, tool_name="PowerShell")
    assert deny_reason(result) == "blocked: api-key in command"


@pytest.mark.parametrize(
    "command",
    [
        "curl -H 'x: nothing' https://example.invalid",
        "curl -H 'Authorization: Bearer not-a-jwt' https://example.invalid",
    ],
)
def test_command_without_a_secret_is_allowed(tmp_path, command):
    assert_allowed(run_hook(command, tmp_path))


@pytest.mark.parametrize(
    "command",
    [
        "git commit -m x",
        "git push",
        "git push origin main",
        "GIT_AUTHOR_NAME=x git commit -m x",
        "git --no-pager commit -m x",
        "echo hi && git commit -m x",
        "git add -A; git push",
        "echo hi\ngit commit -m x",
    ],
)
def test_staged_secret_denies_commit_or_push(repo, command):
    stage(repo, "keys/fixture.pem", PEM)
    result = run_hook(command, repo)
    assert deny_reason(result) == "blocked: pem in staged file keys/fixture.pem"
    output = result.stdout + result.stderr
    assert PEM_HEADER not in output
    assert "FIXTUREONLYFILLER" not in output


@pytest.mark.parametrize(
    "command",
    ["git status", "git log --grep commit", "echo git commit", "git diff --cached"],
)
def test_staged_secret_is_ignored_for_other_commands(repo, command):
    stage(repo, "keys/fixture.pem", PEM)
    assert_allowed(run_hook(command, repo))


@pytest.mark.parametrize("command", ["git commit -m x", "git push"])
def test_clean_staged_file_is_allowed(repo, command):
    stage(repo, "notes.txt", "hello\n")
    assert_allowed(run_hook(command, repo))


def test_only_added_lines_are_scanned(repo):
    stage(repo, "config.txt", f"first\nkey = {API_KEY}\nlast\n")
    git(repo, "commit", "-q", "-m", "base")
    stage(repo, "config.txt", f"first\nkey = {API_KEY}\nlast edited\n")
    assert_allowed(run_hook("git commit -m x", repo))

    stage(repo, "config.txt", f"first\nkey = {API_KEY}TWO\nlast edited\n")
    result = run_hook("git commit -m x", repo)
    assert deny_reason(result) == "blocked: api-key in staged file config.txt"


def test_added_line_starting_with_plus_plus_is_still_scanned(repo):
    stage(repo, "new.txt", "++ " + PEM_HEADER + "\n")
    result = run_hook("git commit -m x", repo)
    assert deny_reason(result) == "blocked: pem in staged file new.txt"


def test_git_failure_blocks_without_forwarding_git_output(tmp_path):
    result = run_hook("git commit -m x", tmp_path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "fatal" not in result.stderr
    assert "not a git repository" not in result.stderr


def test_unreadable_input_fails_without_echoing_it(tmp_path):
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input="not json " + API_KEY,
        capture_output=True,
        text=True,
        env=GIT_ENV,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert API_KEY not in result.stderr


def test_settings_register_the_hook():
    settings = json.loads(SETTINGS.read_text())
    assert "disableAllHooks" not in settings
    groups = settings["hooks"]["PreToolUse"]
    assert len(groups) == 1
    assert groups[0]["matcher"] == "Bash|PowerShell"
    assert len(groups[0]["hooks"]) == 1
    handler = groups[0]["hooks"][0]
    assert handler["type"] == "command"
    assert handler["command"] == "python3"
    assert handler["args"] == ["${CLAUDE_PROJECT_DIR}/.claude/hooks/block_secret.py"]
    assert handler["args"][0].endswith(".claude/hooks/block_secret.py")
    assert handler["onFailure"] == "block"


def test_settings_register_the_stop_hook():
    settings = json.loads(SETTINGS.read_text())
    assert "disableAllHooks" not in settings
    assert len(settings["hooks"]["PreToolUse"]) == 1
    groups = settings["hooks"]["Stop"]
    assert len(groups) == 1
    assert "matcher" not in groups[0]
    assert len(groups[0]["hooks"]) == 1
    handler = groups[0]["hooks"][0]
    assert handler["type"] == "command"
    assert handler["command"] == "python3"
    assert handler["args"] == ["${CLAUDE_PROJECT_DIR}/.claude/hooks/stop_check.py"]
    assert not {"onFailure", "if", "async"} & set(handler)
    lines = (ROOT / ".gitignore").read_text().splitlines()
    assert ".claude/check-passed/" in lines


def hook_scripts():
    scripts = sorted(HOOKS.glob("*.py"))
    assert scripts, "no hook scripts found"
    return scripts


def test_hook_scripts_import_no_network_modules():
    banned = {"socket", "urllib", "http", "requests"}
    for script in hook_scripts():
        imported = set()
        for node in ast.walk(ast.parse(script.read_text())):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
        assert not imported & banned, script.name


def test_sources_never_hold_the_contiguous_key_prefix():
    prefix = "sk-ant-" + "api03-"
    for path in [*hook_scripts(), Path(__file__)]:
        assert prefix not in path.read_text(), path.name


CLEAN_ENV = {
    k: v
    for k, v in GIT_ENV.items()
    if k not in ("HARNESS_LAB_REQUIRE_CHECK", "CLAUDE_PROJECT_DIR")
}
FILLER = "FILLERTEXTSHOULDNEVERAPPEAR"
REFUSED = (
    "HARNESS_LAB_REQUIRE_CHECK=1 and the Stop hook input was refused: "
    "it is not a JSON object with a session id of letters, digits, _ and -."
)


def missing_reason(session_id):
    return (
        "HARNESS_LAB_REQUIRE_CHECK=1 and no passing check marker for this session. "
        f"Run python3 .claude/hooks/record_check.py {session_id} "
        "factory or project:<name>."
    )


def stop_payload(session_id, cwd, **extra):
    return {
        "session_id": session_id,
        "cwd": str(cwd),
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "transcript_path": FILLER + "/transcript.jsonl",
        "last_assistant_message": FILLER,
    } | extra


def run_stop(payload_or_text, *, require=None, project_dir=None):
    text = (
        payload_or_text
        if isinstance(payload_or_text, str)
        else json.dumps(payload_or_text)
    )
    env = dict(CLEAN_ENV)
    if require is not None:
        env["HARNESS_LAB_REQUIRE_CHECK"] = require
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        [sys.executable, str(STOP)],
        input=text,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def write_marker(root, session_id, body):
    marker = root / ".claude" / "check-passed" / session_id
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(body)


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def assert_blocked(result, reason):
    assert result.returncode == 0, result.stderr
    assert (
        result.stdout
        == json.dumps({"decision": "block", "reason": reason}, separators=(",", ":"))
        + "\n"
    )
    assert json.loads(result.stdout) == {"decision": "block", "reason": reason}
    assert "continue" not in json.loads(result.stdout)
    assert FILLER not in result.stdout + result.stderr


def test_stop_does_nothing_when_the_variable_is_unset(tmp_path):
    result = run_stop(stop_payload("abc", tmp_path), project_dir=tmp_path)
    assert result.returncode == 0
    assert result.stdout == ""


def test_stop_blocks_when_the_marker_is_missing(tmp_path):
    result = run_stop(stop_payload("abc", tmp_path), require="1", project_dir=tmp_path)
    assert_blocked(result, missing_reason("abc"))


def test_stop_allows_when_the_marker_passed(tmp_path):
    write_marker(tmp_path, "abc", "passed factory\n")
    result = run_stop(stop_payload("abc", tmp_path), require="1", project_dir=tmp_path)
    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.parametrize("value", ["true", "0", " 1", "1 ", "yes", ""])
def test_stop_ignores_any_value_other_than_one(tmp_path, value):
    result = run_stop(
        stop_payload("abc", tmp_path), require=value, project_dir=tmp_path
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_stop_refuses_unreadable_input_without_echoing_it(tmp_path):
    result = run_stop("not json " + API_KEY, require="1", project_dir=tmp_path)
    assert_blocked(result, REFUSED)
    assert API_KEY not in result.stdout + result.stderr


def test_stop_refuses_a_non_object(tmp_path):
    result = run_stop("[1, 2]", require="1", project_dir=tmp_path)
    assert_blocked(result, REFUSED)


@pytest.mark.parametrize(
    "session_id", ["../x", "a/b", "", "x" * 129, "abc\n", "a b", 7]
)
def test_stop_refuses_a_bad_session_id_and_writes_nothing(tmp_path, session_id):
    before = tree(tmp_path)
    result = run_stop(
        stop_payload(session_id, tmp_path), require="1", project_dir=tmp_path
    )
    assert_blocked(result, REFUSED)
    if isinstance(session_id, str) and session_id.strip():
        assert session_id not in result.stdout
    assert tree(tmp_path) == before


def test_stop_without_a_root_is_refused():
    payload = {"session_id": "abc", "cwd": ""}
    assert_blocked(run_stop(payload, require="1"), REFUSED)
    assert_blocked(run_stop({"session_id": "abc"}, require="1"), REFUSED)


def test_stop_hook_active_does_not_allow(tmp_path):
    payload = stop_payload("abc", tmp_path, stop_hook_active=True)
    result = run_stop(payload, require="1", project_dir=tmp_path)
    assert_blocked(result, missing_reason("abc"))


def test_stop_failed_marker_does_not_allow(tmp_path):
    write_marker(tmp_path, "abc", "failed factory\n")
    result = run_stop(stop_payload("abc", tmp_path), require="1", project_dir=tmp_path)
    assert_blocked(result, missing_reason("abc"))


def test_stop_marker_that_is_a_directory_does_not_allow(tmp_path):
    (tmp_path / ".claude" / "check-passed" / "abc").mkdir(parents=True)
    result = run_stop(stop_payload("abc", tmp_path), require="1", project_dir=tmp_path)
    assert_blocked(result, missing_reason("abc"))


def test_stop_root_prefers_the_project_dir_then_the_input_cwd(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    write_marker(root_a, "abc", "passed factory\n")
    first = run_stop(stop_payload("abc", root_b), require="1", project_dir=root_a)
    assert first.returncode == 0
    assert first.stdout == ""
    second = run_stop(stop_payload("abc", root_a), require="1")
    assert second.returncode == 0
    assert second.stdout == ""
    third = run_stop(stop_payload("abc", root_b), require="1")
    assert_blocked(third, missing_reason("abc"))


def run_record(root, *args, path_prefix=None):
    env = dict(CLEAN_ENV) | {"CLAUDE_PROJECT_DIR": str(root)}
    if path_prefix is not None:
        env["PATH"] = str(path_prefix) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [sys.executable, str(RECORD), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def write_script(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def write_check(root, name, body):
    write_script(root / "projects" / name / "check", body)


def marker_dir(root):
    return root / ".claude" / "check-passed"


def test_record_writes_only_the_fixed_marker_text(tmp_path):
    write_check(tmp_path, "demo", f"echo {API_KEY}\necho {API_KEY} >&2\nexit 0\n")
    result = run_record(tmp_path, "sess-1", "project:demo")
    assert result.returncode == 0
    marker = marker_dir(tmp_path) / "sess-1"
    assert marker.read_text() == "passed project:demo\n"
    assert API_KEY not in marker.read_text()


def test_record_failing_check_writes_nothing(tmp_path):
    write_check(tmp_path, "demo", "exit 1\n")
    result = run_record(tmp_path, "sess-1", "project:demo")
    assert result.returncode != 0
    assert not marker_dir(tmp_path).exists()


def test_record_exit_code_follows_the_check(tmp_path):
    write_check(tmp_path, "demo", "exit 7\n")
    assert run_record(tmp_path, "sess-1", "project:demo").returncode == 7


def test_record_wrong_argument_count_is_a_usage_error(tmp_path):
    assert run_record(tmp_path).returncode == 2
    assert run_record(tmp_path, "sess-1").returncode == 2
    assert run_record(tmp_path, "a", "factory", "extra").returncode == 2
    assert not (tmp_path / ".claude").exists()


@pytest.mark.parametrize(
    "selector",
    ["project:../x", "project:", "project:Demo", "project:missing", "nonsense"],
)
def test_record_refuses_a_bad_selector(tmp_path, selector):
    root = tmp_path / "root"
    sentinel = tmp_path / "sentinel"
    write_script(tmp_path / "x" / "check", f"echo ran > {sentinel}\nexit 0\n")
    write_script(root / "x" / "check", f"echo ran > {sentinel}\nexit 0\n")
    write_check(root, "demo", f"echo ran > {sentinel}\nexit 0\n")
    result = run_record(root, "sess-1", selector)
    assert result.returncode == 2
    assert "unknown selector" in result.stderr
    assert selector not in result.stderr
    assert not sentinel.exists()
    assert not (root / ".claude").exists()


def test_record_refuses_a_check_symlinked_out_of_its_directory(tmp_path):
    root = tmp_path / "root"
    sentinel = tmp_path / "sentinel"
    outside = tmp_path / "outside" / "check"
    write_script(outside, f"echo ran > {sentinel}\nexit 0\n")
    (root / "projects" / "link").mkdir(parents=True)
    (root / "projects" / "link" / "check").symlink_to(outside)
    result = run_record(root, "sess-1", "project:link")
    assert result.returncode == 2
    assert not sentinel.exists()
    assert not (root / ".claude").exists()


@pytest.mark.parametrize("session_id", ["../x", "a/b", "x" * 129])
def test_record_refuses_a_bad_session_id_before_running_anything(tmp_path, session_id):
    root = tmp_path / "root"
    sentinel = tmp_path / "sentinel"
    write_check(root, "demo", f"echo ran > {sentinel}\nexit 0\n")
    result = run_record(root, session_id, "project:demo")
    assert result.returncode == 2
    assert session_id not in result.stderr
    assert not sentinel.exists()
    assert not (root / ".claude").exists()
    assert not (root / "x").exists()
    assert not (tmp_path / "x").exists()


def test_record_factory_runs_uv_pytest_in_the_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    bin_dir = tmp_path / "bin"
    log = tmp_path / "uv.log"
    write_script(
        bin_dir / "uv",
        f'for a in "$@"; do echo "$a"; done > {log}\npwd -P >> {log}\nexit 0\n',
    )
    result = run_record(root, "sess-1", "factory", path_prefix=bin_dir)
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [
        "run",
        "pytest",
        "tests/factory",
        str(root.resolve()),
    ]
    assert (marker_dir(root) / "sess-1").read_text() == "passed factory\n"


def test_record_then_stop_allows_the_session(tmp_path):
    write_check(tmp_path, "demo", "exit 0\n")
    assert run_record(tmp_path, "sess-1", "project:demo").returncode == 0
    result = run_stop(
        stop_payload("sess-1", tmp_path), require="1", project_dir=tmp_path
    )
    assert result.returncode == 0
    assert result.stdout == ""
