"""Review's own daily cap, and the comment a capped Review leaves on the PR."""

import argparse
import json
import os
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from factory import review_pr
from factory.review_pr import MARKER, capped
from tests.factory.support import REPO, SHA, FakeGitHub

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION = ROOT / ".github" / "actions" / "factory-preflight" / "action.yml"
OTHERS = ["implement", "rework", "research", "ci-gate", "factory-check"]


def _args(head: str = SHA) -> list[str]:
    return [
        "capped",
        "--repo",
        REPO,
        "--pr",
        "5",
        "--head-sha",
        head,
        "--cap",
        "40",
        "--variable",
        "FACTORY_REVIEW_DAILY_RUN_CAP",
    ]


def test_capped_review_posts_one_comment_per_head_and_no_review_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = FakeGitHub()
    monkeypatch.setattr(review_pr, "GitHub", lambda: gh)
    assert review_pr.main(_args()) == 0
    assert review_pr.main(_args()) == 0
    assert len(gh.posted) == 1
    number, body = gh.posted[0]
    assert number == 5
    assert MARKER not in body
    assert review_pr.review_verdict(body) is None
    assert review_pr.review_input(gh.pr_comments(REPO, 5)) is None
    assert "FACTORY_REVIEW_DAILY_RUN_CAP" in body and "40" in body
    assert review_pr.review_passed(gh.pr_comments(REPO, 5), SHA) is False


def test_a_new_head_gets_its_own_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    gh = FakeGitHub()
    monkeypatch.setattr(review_pr, "GitHub", lambda: gh)
    other = "b" * 40
    for head in (SHA, other, SHA, other):
        assert review_pr.main(_args(head)) == 0
    assert len(gh.posted) == 2


def test_capped_takes_a_fake_github_directly() -> None:
    gh = FakeGitHub()
    ns = argparse.Namespace(repo=REPO, pr=5, head_sha=SHA, cap="40", variable="V")
    assert capped(ns, gh) == 0  # type: ignore[arg-type]
    assert len(gh.posted) == 1


def test_review_yml_has_its_own_cap_and_the_others_keep_theirs() -> None:
    review = (WORKFLOWS / "review.yml").read_text()
    assert "daily-run-cap: ${{ vars.FACTORY_REVIEW_DAILY_RUN_CAP || '40' }}" in review
    assert "vars.FACTORY_DAILY_RUN_CAP" not in review
    for name in OTHERS:
        text = (WORKFLOWS / f"{name}.yml").read_text()
        assert "daily-run-cap: ${{ vars.FACTORY_DAILY_RUN_CAP || '20' }}" in text, name
        assert "FACTORY_REVIEW_DAILY_RUN_CAP" not in text, name
        assert "continue-on-cap" not in text, name


def test_review_yml_posts_with_the_app_token_then_fails_and_gates_the_agent_steps() -> (
    None
):
    text = (WORKFLOWS / "review.yml").read_text()
    assert 'continue-on-cap: "true"' in text
    post = text.split(
        "- name: Say on the PR that the daily cap stopped this review", 1
    )[1]
    post = post.split("\n      - name:", 1)[0]
    assert "steps.preflight.outputs.token" in post and "github.token" not in post
    stop = text.split("- name: Stop, red, because the daily cap was reached", 1)[1]
    assert "exit 1" in stop.split("\n      - name:", 1)[0]
    for step in (
        "Check out the pull request",
        "Install Claude Code",
        "Gather the diff",
        "Review (fresh context",
        "Read CI for this head",
        "Post the report",
    ):
        block = text.split(f"- name: {step}", 1)[1].split("\n      - ", 1)[0]
        assert "steps.preflight.outputs.capped != 'true'" in block, step
    job_permissions = text.split("    permissions:\n", 1)[1].split("steps:", 1)[0]
    assert "write" not in job_permissions


def _cap_script() -> str:
    block = ACTION.read_text().split("- name: Enforce the daily run cap", 1)[1]
    run = block.split("      run: |\n", 1)[1].split("\n    - name:", 1)[0]
    return "\n".join(line[8:] for line in run.splitlines())


def _fake_gh(tmp_path: Path, runs: list[dict[str, Any]]) -> Path:
    """A `gh` that answers `run list` from `runs`: it applies --created and --jq as gh does."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    runs_file = tmp_path / "runs.json"
    runs_file.write_text(json.dumps(runs))
    gh = bindir / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, subprocess, sys\n"
        "a = sys.argv[1:]\n"
        "since = a[a.index('--created') + 1].lstrip('>=')\n"
        f"runs = [r for r in json.load(open({str(runs_file)!r}))\n"
        "        if r['createdAt'][:10] >= since]\n"
        "print(subprocess.run(['jq', '-r', a[a.index('--jq') + 1]], input=json.dumps(runs),\n"
        "                     capture_output=True, text=True, check=True).stdout, end='')\n"
    )
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return bindir


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _runs(states: list[str]) -> list[dict[str, Any]]:
    stamp = f"{_today()}T00:00:01Z"
    return [
        {
            "databaseId": i + 1,
            "createdAt": stamp,
            "status": s,
            "conclusion": "success" if s == "completed" else "",
        }
        for i, s in enumerate(states)
    ]


def _run_cap(
    tmp_path: Path, runs: list[dict[str, Any]], cap: str, continue_on_cap: str = "false"
) -> tuple["subprocess.CompletedProcess[str]", str]:
    bindir = _fake_gh(tmp_path, runs)
    output = tmp_path / "github_output"
    output.write_text("")
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_OUTPUT": str(output),
        "CAP": cap,
        "RUN_ID": "900",
        "WORKFLOW_REF": f"{REPO}/.github/workflows/review.yml@refs/heads/main",
        "CAP_VARIABLE": "FACTORY_REVIEW_DAILY_RUN_CAP",
        "CONTINUE_ON_CAP": continue_on_cap,
    }
    done = subprocess.run(
        ["bash", "-c", _cap_script()],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return done, output.read_text()


def test_queued_and_running_runs_count_toward_the_cap(tmp_path: Path) -> None:
    runs = _runs(["queued", "in_progress", "completed"])
    # This run itself is never counted, and a run from before 00:00 UTC today is not today's.
    runs.append(
        {
            "databaseId": 900,
            "createdAt": f"{_today()}T01:00:00Z",
            "status": "in_progress",
            "conclusion": "",
        }
    )
    runs.append(
        {
            "databaseId": 50,
            "createdAt": "2000-01-01T00:00:00Z",
            "status": "queued",
            "conclusion": "",
        }
    )
    done, _ = _run_cap(tmp_path, runs, "3")
    assert done.returncode == 1
    text = done.stdout + done.stderr
    assert "started 3 runs today" in text
    assert "FACTORY_REVIEW_DAILY_RUN_CAP" in text


def test_one_run_under_the_cap_the_step_passes_and_says_not_capped(
    tmp_path: Path,
) -> None:
    done, out = _run_cap(tmp_path, _runs(["queued", "in_progress"]), "3")
    assert done.returncode == 0, done.stderr
    assert "capped=false" in out


def test_continue_on_cap_sets_the_output_instead_of_failing(tmp_path: Path) -> None:
    done, out = _run_cap(tmp_path, _runs(["queued", "in_progress"]), "2", "true")
    assert done.returncode == 0, done.stderr
    assert out.strip().splitlines()[-1] == "capped=true"
