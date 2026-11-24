"""The commit status `factory/review`: the pure mapping, the handoff and the workflow's shape."""

from pathlib import Path
from typing import Optional

import pytest

from factory import review_pr, review_status
from factory.review_status import REASONS, pick, status_for
from tests.factory.support import REPO, SHA, FakeGitHub

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github" / "workflows" / "review.yml").read_text()
STATUS_JOB = WORKFLOW.split("\n  status:\n")[1]
REVIEW_JOB = WORKFLOW.split("\n  review:\n")[1].split("\n  # Sets the commit status")[0]


def test_pass_is_success_and_blocked_is_failure() -> None:
    assert status_for("PASS", None)[0] == "success"
    assert status_for("BLOCKED", None)[0] == "failure"


def test_each_reason_is_an_error_with_its_own_description() -> None:
    results = [status_for(None, reason) for reason in REASONS]
    assert {state for state, _ in results} == {"error"}
    assert len({description for _, description in results}) == len(REASONS)


@pytest.mark.parametrize("reason", REASONS)
def test_a_reason_without_a_verdict_is_an_error(reason: str) -> None:
    state, description = status_for(None, reason)
    assert state == "error" and 0 < len(description) <= 140


def test_unknown_input_is_an_error() -> None:
    assert status_for("MAYBE", None)[0] == "error"
    assert status_for(None, "because")[0] == "error"
    assert status_for(None, None)[0] == "error"


@pytest.mark.parametrize(
    ("verdict", "reason", "result", "expected"),
    [
        ("", "capped", "failure", (None, "capped")),
        ("", "timed-out", "failure", (None, "timed-out")),
        ("", "stale-head", "success", (None, "stale-head")),
        ("PASS", "", "success", ("PASS", None)),
        ("BLOCKED", "", "success", ("BLOCKED", None)),
        ("", "", "cancelled", (None, "crashed")),
        ("", "", "failure", (None, "crashed")),
        ("", "", "success", (None, "no-verdict")),
        ("junk", "junk", "success", (None, "no-verdict")),
        ("", "", "weird", (None, "crashed")),
    ],
)
def test_pick_uses_what_was_handed_over_else_how_review_ended(
    verdict: str,
    reason: str,
    result: str,
    expected: tuple[Optional[str], Optional[str]],
) -> None:
    assert pick(verdict, reason, result) == expected


def test_capped_crashed_and_timed__out_reviews_give_error() -> None:
    for verdict, reason, result in [
        ("", "capped", "failure"),
        ("", "", "failure"),
        ("", "", "cancelled"),
        ("", "timed-out", "failure"),
    ]:
        assert status_for(*pick(verdict, reason, result))[0] == "error"


def _outputs(capsys: pytest.CaptureFixture[str]) -> dict[str, str]:
    lines = capsys.readouterr().out.splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def test_resolve_targets_the_comment_else_the_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = "https://github.com/o/r/actions/runs/9"
    args = ["resolve", "--repo", "o/r", "--pr", "4", "--run-url", run]
    assert review_status.main([*args, "--verdict", "PASS", "--comment-id", "77"]) == 0
    got = _outputs(capsys)
    assert got["state"] == "success"
    assert got["target-url"] == "https://github.com/o/r/pull/4#issuecomment-77"
    assert review_status.main([*args, "--review-result", "failure"]) == 0
    got = _outputs(capsys)
    assert got["state"] == "error" and got["target-url"] == run


def _applied(tmp_path: Path, head: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run `apply` against a fake PR whose head is `head`; the Review read SHA."""
    out = tmp_path / "review-out"
    out.mkdir()
    (out / "context.json").write_text(f'{{"head_sha": "{SHA}", "ticket": 7}}')
    answer = (Path(__file__).parent / "review-answer.json").read_text()
    (out / "findings.json").write_text(answer)
    gh = FakeGitHub(head=head)
    review_pr.apply(_Args(out), gh)  # type: ignore[arg-type]
    return out


class _Args:
    def __init__(self, out: Path) -> None:
        self.out, self.repo, self.pr = str(out), REPO, 5


def test_apply_leaves_the_comment_id_and_handoff_reads_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _applied(tmp_path, SHA, monkeypatch)
    assert (out / "comment-id.txt").read_text().strip().isdigit()
    capsys.readouterr()
    assert review_status.handoff(out, capped=False) == 0
    got = _outputs(capsys)
    assert got["verdict"] in ("PASS", "BLOCKED")
    assert got["comment-id"].isdigit() and got["reason"] == ""


def test_a_stale_head_is_handed_over_as_a_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _applied(tmp_path, "b" * 40, monkeypatch)
    capsys.readouterr()
    review_status.handoff(out, capped=False)
    assert _outputs(capsys)["reason"] == "stale-head"


def test_a_capped_review_hands_over_capped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    review_status.handoff(tmp_path, capped=True)
    got = _outputs(capsys)
    assert (
        got["reason"] == "capped" and got["verdict"] == "" and got["comment-id"] == ""
    )


def test_handoff_with_nothing_written_hands_over_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    review_status.handoff(tmp_path, capped=False)
    assert set(_outputs(capsys).values()) == {""}


def test_statuses_write_is_only_in_the_status_job() -> None:
    assert WORKFLOW.count("statuses: write") == 1
    assert "statuses: write" in STATUS_JOB and "statuses" not in REVIEW_JOB
    assert "permissions: {}" in WORKFLOW.split("\njobs:")[0]


def test_the_status_job_holds_no_agent_secret_or_pr_code() -> None:
    lowered = STATUS_JOB.lower()
    for text in (
        "claude",
        "claude_code_oauth_token",
        "secrets.",
        "pr/",
        "factory-preflight",
    ):
        assert text not in lowered
    assert "persist-credentials: false" in STATUS_JOB
    assert "github.event.repository.default_branch" in STATUS_JOB
    assert "${{ github.token }}" in STATUS_JOB
    assert "github.event.pull_request.head.sha" in STATUS_JOB


def test_the_status_job_runs_always_after_review_but_not_for_a_fork() -> None:
    header = STATUS_JOB.split("steps:")[0]
    assert "needs: review" in header
    assert "if: always() && needs.review.result != 'skipped'" in header
    assert "head.repo.full_name == github.repository" in REVIEW_JOB.split("steps:")[0]


def test_the_handoff_is_the_last_step_of_the_review_job() -> None:
    assert REVIEW_JOB.index("Keep the review's files") < REVIEW_JOB.index(
        "Hand the outcome"
    )
    assert REVIEW_JOB.rstrip().splitlines()[-1].lstrip().startswith("run:")
    for name in ("verdict", "reason", "comment-id"):
        assert f"{name}: ${{{{ steps.handoff.outputs.{name} }}}}" in REVIEW_JOB
