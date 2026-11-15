"""The Rework run's Run record (ticket #144), tested at the last step's entry point."""
import argparse
import json
from pathlib import Path

import pytest

from factory import run_record
from factory.review_pr import MARKER, review_input
from tests.factory.test_run_record import (REPO, RUN_URL, SHA, FakeGitHub, _bot, _built, _line,
                                           _marker)


def _step(out, gh, round_=1, **kw):
    """What the workflow's last step passes to `run_record write --workflow rework`."""
    base = dict(workflow="rework", out=str(out), repo=REPO, run_id="888", attempt="1",
                issue=4, pr=9, pr_labels=json.dumps(["rework", f"rework:{round_}"]),
                project="harness", login="subscription", model="sonnet", budget="5",
                claude_code_version="2.1.319", app_slug="harness-factory", run_url=RUN_URL,
                job_status="success", build_outcome="success", verify_outcome="skipped",
                publish_outcome="success")
    base.update(kw)
    return run_record.write(argparse.Namespace(**base), gh)


def _record(out):
    return json.loads((out / "run.json").read_text())


def test_a_round_that_pushed_leaves_an_ok_record_and_one_line_on_the_pull_request(tmp_path):
    out = _built(tmp_path, _line("result-success.json"))
    gh = FakeGitHub([_bot(5, "A review\n")])
    assert _step(out, gh) == 0
    record = _record(out)
    (number, body), = gh.posted
    assert number == 9 and len(body.splitlines()) == 1
    assert body.startswith(f"Rework round 1 pushed `{SHA[:7]}`.") and RUN_URL in body
    assert _marker(body) == record
    assert gh.thread[0]["body"] == "A review\n"
    assert record["workflow"] == "rework" and record["outcome"] == "ok"
    assert record["reason"] is None and record["head_sha"] == SHA
    assert (record["pr"], record["issue"], record["round"]) == (9, 4, 1)
    assert (record["turns"], record["cost_usd"]) == (5, 0.1289566)
    assert record["verdict"] is None and record["gate"] is None


def _failed(tmp_path, reason_kw, message=None, subtype="success", success=True, files=()):
    out = _built(tmp_path, message or {}, success, subtype)
    for name in files:
        (out / name).write_text("nothing changed\n")
    gh = FakeGitHub()
    assert _step(out, gh, **reason_kw) == 0
    record = _record(out)
    (number, body), = gh.posted
    assert number == 9 and len(body.splitlines()) == 1 and _marker(body) == record
    assert body.startswith(f"Rework round 1 failed: `{record['reason']}`.") and RUN_URL in body
    assert record["outcome"] == "fail" and record["head_sha"] is None
    assert (record["pr"], record["issue"]) == (9, 4)
    return record


def test_a_cli_error_subtype_is_a_failed_round(tmp_path):
    record = _failed(tmp_path, dict(build_outcome="failure", job_status="failure",
                                    publish_outcome="skipped"),
                     _line("result-budget-stop.json"), "error_max_budget_usd", False)
    assert record["reason"] == "error_max_budget_usd" and record["cost_usd"] == 0.004602


def test_a_round_that_changed_nothing_is_no_change(tmp_path):
    record = _failed(tmp_path, dict(publish_outcome="failure", job_status="failure"),
                     _line("result-success.json"), files=("unchanged.md",))
    assert record["reason"] == "no-change"


def test_a_failed_check_is_check_failed(tmp_path):
    record = _failed(tmp_path, dict(verify_outcome="failure", job_status="failure",
                                    publish_outcome="skipped"), _line("result-success.json"))
    assert record["reason"] == "check-failed"


def test_a_failed_push_is_publish_failed(tmp_path):
    record = _failed(tmp_path, dict(publish_outcome="failure", job_status="failure"),
                     _line("result-success.json"))
    assert record["reason"] == "publish-failed"


def test_a_cancelled_round_is_a_failed_round(tmp_path):
    record = _failed(tmp_path, dict(job_status="cancelled", build_outcome="cancelled",
                                    publish_outcome="skipped"), _line("result-success.json"))
    assert record["reason"] == "cancelled"


@pytest.mark.parametrize("round_", [1, 2])
def test_the_round_is_the_rework_label_the_run_started_with(tmp_path, round_):
    out = _built(tmp_path, _line("result-success.json"))
    gh = FakeGitHub()
    _step(out, gh, round_=round_)
    assert _record(out)["round"] == round_
    assert f"Rework round {round_} pushed" in gh.posted[0][1]


def test_a_file_in_the_output_directory_cannot_choose_the_round_or_the_pull_request(tmp_path):
    out = _built(tmp_path, _line("result-success.json"))
    (out / "context.json").write_text(json.dumps({"pr": 1, "issue": 1, "round": 2}))
    gh = FakeGitHub()
    _step(out, gh, round_=1)
    record = _record(out)
    assert (record["pr"], record["issue"], record["round"]) == (9, 4, 1)
    assert gh.posted[0][0] == 9


def test_review_input_ignores_the_new_comments(tmp_path):
    out = _built(tmp_path, _line("result-success.json"))
    review = f"{MARKER}\n<!-- factory:gate head={SHA} charged=1 source=review -->\nBLOCKED\n"
    for publish in ("success", "failure"):
        gh = FakeGitHub()
        _step(out, gh, publish_outcome=publish, job_status="success")
        assert MARKER not in gh.posted[0][1]
        assert review_input([_bot(1, review)] + gh.thread, SHA) == review
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
