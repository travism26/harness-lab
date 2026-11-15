"""The Rework run's Run record (ticket #144), tested at the last step's entry point."""
import json
from pathlib import Path

import pytest

from factory import run_record
from factory.review_pr import MARKER, review_input
from tests.factory.support import (REPO, RUN_URL, SHA, FakeGitHub, bot_comment, built,
                                   failed_out, fixture_line, marker_of, record_of, step_args)

def _labels(round_):
    """The event's labels for a pull request in `round_` (0 is a rework label with no counter)."""
    return json.dumps(["rework", f"rework:{round_}"] if round_ else ["rework"])


def _step(out, gh, round_=1, **kw):
    """What the workflow's last step passes to `run_record write --workflow rework`."""
    kw.setdefault("pr_labels", _labels(round_))
    base = dict(run_id="888", pr=9)
    base.update(kw)
    return run_record.write(step_args("rework", out, **base), gh)


def test_a_round_that_pushed_leaves_an_ok_record_and_the_marker_on_a_line_of_its_own(tmp_path):
    out = built(tmp_path, fixture_line("result-success.json"))
    gh = FakeGitHub([bot_comment(5, "A review\n")])
    assert _step(out, gh) == 0
    record = record_of(out)
    (number, body), = gh.posted
    assert number == 9 and len(body.splitlines()) == 2
    assert body.startswith(f"Rework round 1 pushed `{SHA[:7]}`.") and RUN_URL in body
    assert marker_of(body) == record and body.splitlines()[-1].startswith("<!-- factory:run ")
    assert gh.thread[0]["body"] == "A review\n"
    assert record["workflow"] == "rework" and record["outcome"] == "ok"
    assert record["reason"] is None and record["head_sha"] == SHA
    assert (record["pr"], record["issue"], record["round"]) == (9, 4, 1)
    assert (record["turns"], record["cost_usd"]) == (5, 0.1289566)
    assert record["verdict"] is None and record["gate"] is None


def _failed(tmp_path, reason_kw, message=None, subtype="success", success=True, files=()):
    out = failed_out(tmp_path, message, subtype, success, files)
    gh = FakeGitHub()
    assert _step(out, gh, **reason_kw) == 0
    record = record_of(out)
    (number, body), = gh.posted
    assert number == 9 and len(body.splitlines()) == 2 and marker_of(body) == record
    assert body.startswith(f"Rework round 1 failed: `{record['reason']}`.") and RUN_URL in body
    assert record["outcome"] == "fail" and record["head_sha"] is None
    assert (record["pr"], record["issue"]) == (9, 4)
    return record


def test_a_cli_error_subtype_is_a_failed_round(tmp_path):
    record = _failed(tmp_path, dict(agent_outcome="failure", job_status="failure",
                                    publish_outcome="skipped"),
                     fixture_line("result-budget-stop.json"), "error_max_budget_usd", False)
    assert record["reason"] == "error_max_budget_usd" and record["cost_usd"] == 0.004602


def test_a_round_that_changed_nothing_is_no_change(tmp_path):
    record = _failed(tmp_path, dict(publish_outcome="failure", job_status="failure"),
                     fixture_line("result-success.json"), files=("unchanged.md",))
    assert record["reason"] == "no-change"


def test_a_failed_check_is_check_failed(tmp_path):
    record = _failed(tmp_path, dict(verify_outcome="failure", job_status="failure",
                                    publish_outcome="skipped"),
                     fixture_line("result-success.json"))
    assert record["reason"] == "check-failed"


def test_a_failed_push_is_publish_failed(tmp_path):
    record = _failed(tmp_path, dict(publish_outcome="failure", job_status="failure"),
                     fixture_line("result-success.json"))
    assert record["reason"] == "publish-failed"


def test_a_cancelled_round_is_a_failed_round(tmp_path):
    record = _failed(tmp_path, dict(job_status="cancelled", agent_outcome="cancelled",
                                    publish_outcome="skipped"),
                     fixture_line("result-success.json"))
    assert record["reason"] == "cancelled"


@pytest.mark.parametrize("round_", [1, 2])
def test_the_round_is_the_rework_label_the_run_started_with(tmp_path, round_):
    out = built(tmp_path, fixture_line("result-success.json"))
    gh = FakeGitHub()
    _step(out, gh, round_=round_)
    assert record_of(out)["round"] == round_
    assert f"Rework round {round_} pushed" in gh.posted[0][1]


def test_a_round_the_events_labels_do_not_hold_is_read_from_the_pull_request(tmp_path):
    """Code review B4: the labels in the event hold no `rework:N`."""
    out = built(tmp_path, fixture_line("result-success.json"))
    gh = FakeGitHub(labels=["rework", "rework:2"])
    _step(out, gh, round_=0)
    assert record_of(out)["round"] == 2
    assert "Rework round 2 pushed" in gh.posted[0][1]


def test_a_round_neither_the_event_nor_the_pull_request_holds_is_null(tmp_path):
    out = built(tmp_path, fixture_line("result-success.json"))
    _step(out, FakeGitHub(), round_=0)
    assert record_of(out)["round"] is None


def test_the_events_round_wins_over_a_live_read(tmp_path):
    out = built(tmp_path, fixture_line("result-success.json"))
    _step(out, FakeGitHub(labels=["rework:2"]), round_=1)
    assert record_of(out)["round"] == 1


def test_a_head_branch_that_is_not_a_factory_branch_gives_a_null_issue(tmp_path, monkeypatch):
    """Code review B4: the workflow passes `${HEAD_REF#factory/issue-}`, which leaves a branch
    that is not `factory/issue-<N>` whole."""
    out = built(tmp_path, fixture_line("result-success.json"))
    monkeypatch.setattr(run_record, "GitHub", FakeGitHub)

    def issue_of(head_ref_rest):
        argv = ["write", "--workflow", "rework", "--out", str(out), "--repo", REPO,
                "--run-id", "888", "--attempt", "1", "--issue", head_ref_rest, "--pr", "9",
                "--pr-labels", _labels(1), "--project", "", "--login", "subscription",
                "--model", "sonnet", "--budget", "5", "--claude-code-version", "2.1.319",
                "--app-slug", "harness-factory", "--run-url", RUN_URL, "--job-status", "success",
                "--agent-outcome", "success", "--publish-outcome", "success"]
        assert run_record.main(argv) == 0
        return record_of(out)["issue"]

    assert issue_of("feature/not-a-ticket") is None
    assert issue_of("12") == 12


def test_a_file_in_the_output_directory_cannot_choose_the_round_or_the_pull_request(tmp_path):
    out = built(tmp_path, fixture_line("result-success.json"))
    (out / "context.json").write_text(json.dumps({"pr": 1, "issue": 1, "round": 2}))
    gh = FakeGitHub()
    _step(out, gh, round_=1)
    record = record_of(out)
    assert (record["pr"], record["issue"], record["round"]) == (9, 4, 1)
    assert gh.posted[0][0] == 9


def test_review_input_ignores_the_new_comments(tmp_path):
    out = built(tmp_path, fixture_line("result-success.json"))
    review = f"{MARKER}\n<!-- factory:gate head={SHA} charged=1 source=review -->\nBLOCKED\n"
    for publish in ("success", "failure"):
        gh = FakeGitHub()
        _step(out, gh, publish_outcome=publish, job_status="success")
        assert MARKER not in gh.posted[0][1]
        assert review_input([bot_comment(1, review)] + gh.thread, SHA) == review
    assert review_input(gh.thread, SHA) is None


def test_rework_workflow_runs_the_last_step_after_publish_and_before_the_upload():
    text = (Path(__file__).resolve().parents[2] / ".github/workflows/rework.yml").read_text()
    publish = text.index("python -m factory.ticket publish")
    last = text.index("python -m factory.run_record write --workflow rework")
    upload = text.index("actions/upload-artifact")
    assert publish < last < upload
    step = text[text.rindex("      - name:", 0, last):upload]
    assert "if: always() && steps.build.conclusion != 'skipped'" in step
    assert "secrets." not in step and "CLAUDE_CODE_OAUTH_TOKEN" not in step
    assert "claude" not in step.replace("claude-code-version", "").replace("CLAUDE_CODE_VERSION", "")
    for step_id in ("build", "verify", "publish"):
        assert f"id: {step_id}\n" in text
