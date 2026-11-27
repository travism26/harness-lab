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
