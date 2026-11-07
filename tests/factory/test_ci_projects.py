import json
import subprocess

import pytest

from factory.ci_projects import main, projects_to_check


ALL = ["agent-identity", "harness"]


@pytest.mark.parametrize(
    "changed, expected",
    [
        (["projects/harness/src/harness/loop.py"], ["harness"]),
        (["projects/harness/check", "projects/agent-identity/go.mod"], ALL),
        (["README.md", "docs/adr/0001-x.md", "tests/factory/test_ticket.py"], []),
        ([], []),
        (["factory/ticket.py"], ALL),
        ([".github/workflows/ci.yml"], ALL),
        ([".github/actions/factory-preflight/action.yml"], ALL),
        (["pyproject.toml"], ALL),
        (["uv.lock"], ALL),
        # A deleted project, or a stray file directly under projects/, checks nothing.
        (["projects/gone/check", "projects/notes.md"], []),
    ],
)
def test_projects_to_check(changed, expected):
    assert projects_to_check(changed, ALL) == expected


def _repo(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    for name in ALL:
        (tmp_path / "projects" / name).mkdir(parents=True)
        (tmp_path / "projects" / name / "check").write_text("#!/bin/sh\n")
    (tmp_path / "projects" / "draft").mkdir()  # no check: not a Project yet
    (tmp_path / "projects" / "draft" / "notes.md").write_text("x\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "projects" / "harness" / "check").write_text("#!/bin/sh\nexit 0\n")
    git("commit", "-qam", "change harness")
    return base


def _run(tmp_path, capsys, base):
    assert main(["--root", str(tmp_path), "--base", base]) == 0
    return json.loads(capsys.readouterr().out)


def test_main_prints_changed_projects_as_json(tmp_path, capsys):
    base = _repo(tmp_path)
    assert _run(tmp_path, capsys, base) == ["harness"]


@pytest.mark.parametrize("base", ["", "0" * 40])
def test_main_without_a_base_checks_every_project(tmp_path, capsys, base):
    _repo(tmp_path)
    assert _run(tmp_path, capsys, base) == ALL
