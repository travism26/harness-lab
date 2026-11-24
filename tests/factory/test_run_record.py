"""Run records (docs/adr/0010-run-records-live-in-comment-markers.md), tested at the
steps' entry points: build saves the raw numbers; run_record.write is the last step."""

import contextlib
import io
import json
from pathlib import Path

import pytest

from factory import metrics, record, run_record, ticket
from factory.record import RunContext
from tests.factory.support import (
    FIXTURES,
    REPO,
    RUN_URL,
    SHA,
    TOKEN,
    FakeGitHub,
    bot_comment,
    built,
    failed_out,
    fixture_line,
    marker_of,
    record_of,
    step_args,
    token_shaped,
)

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def test_build_saves_only_the_numbers_from_the_result_line(tmp_path):
    message = dict(
        fixture_line("result-success.json"), result="MODEL TEXT secret words"
    )
    out = built(tmp_path, message)
    saved = json.loads((out / "result.json").read_text())
    assert (
        saved["num_turns"] == 5 and saved["usage"]["cache_read_input_tokens"] == 94606
    )
    assert "MODEL TEXT" not in (out / "result.json").read_text()
    assert "secret words" not in (out / "result.json").read_text()


def test_build_saves_the_numbers_when_the_agent_fails(tmp_path):
    out = built(
        tmp_path, fixture_line("result-budget-stop.json"), False, "error_max_budget_usd"
    )
    assert (
        json.loads((out / "result.json").read_text())["subtype"]
        == "error_max_budget_usd"
    )


# ---- the last step ------------------------------------------------------------

OPENED = f"The factory opened a draft PR: https://github.com/{REPO}/pull/9\n"
FAILED = (
    f"The factory run for this Ticket failed: [run]({RUN_URL}). `in-progress` has been "
    "removed; re-apply `ready-for-factory` to try again.\n"
)
GONE = dict(agent_outcome="failure", job_status="failure", publish_outcome="skipped")


def _last(out, gh, **kw):
    return run_record.write(step_args("implement", out, **kw), gh)


def test_an_opened_draft_leaves_a_record_in_a_file_and_on_the_opened_comment(tmp_path):
    out = built(tmp_path, fixture_line("result-success.json"))
    gh = FakeGitHub(
        [
            bot_comment(5, "The factory started this Ticket. [Run](x)\n"),
            bot_comment(6, OPENED),
        ]
    )
    assert _last(out, gh) == 0
    record_ = record_of(out)
    assert record_ == marker_of(gh.thread[1]["body"])
    assert gh.thread[1]["body"].startswith(OPENED)
    assert "factory:run" not in gh.thread[0]["body"] and gh.posted == []
    assert record_["outcome"] == "ok" and record_["reason"] is None
    assert record_["pr"] == 9 and record_["head_sha"] == SHA and record_["issue"] == 4
    assert record_["model_ids"] == ["claude-sonnet-5-5"]
    assert (record_["turns"], record_["duration_ms"], record_["cost_usd"]) == (
        5,
        40915,
        0.1289566,
    )
    assert (record_["input_tokens"], record_["output_tokens"]) == (10, 4592)
    assert (
        record_["cache_creation_input_tokens"],
        record_["cache_read_input_tokens"],
    ) == (18389, 94606)
    assert record_["cost_note"] == "client-estimate" and record_["round"] == 0
    assert record_["verdict"] is None and record_["gate"] is None
    assert record_["schema"] == 1 and record_["workflow"] == "implement"
    assert (
        record_["run_id"] == 777 and record_["attempt"] == 1 and record_["repo"] == REPO
    )
    assert record_["login"] == "subscription" and record_["model"] == "sonnet"
    assert record_["budget"] == 5 and record_["claude_code_version"] == "2.1.319"
    assert record_["project"] == "harness" and record_["ts"].endswith("Z")
    assert len(record_) == 28


def _failed(
    tmp_path, reason_kw, message=None, subtype="success", success=True, files=()
):
    out = failed_out(tmp_path, message, subtype, success, files)
    gh = FakeGitHub([bot_comment(5, FAILED)])
    assert _last(out, gh, **reason_kw) == 0
    record_ = record_of(out)
    assert record_ == marker_of(gh.thread[0]["body"])
    assert gh.thread[0]["body"].startswith(FAILED) and gh.posted == []
    assert (
        record_["outcome"] == "fail"
        and record_["pr"] is None
        and record_["head_sha"] is None
    )
    return record_


def test_a_cli_error_subtype_is_the_reason_and_the_budget_stop_tokens_come_from_model_usage(
    tmp_path,
):
    record_ = _failed(
        tmp_path,
        GONE,
        fixture_line("result-budget-stop.json"),
        "error_max_budget_usd",
        False,
    )
    assert record_["reason"] == "error_max_budget_usd"
    assert record_["model_ids"] == ["claude-haiku-5-5"]
    assert (record_["input_tokens"], record_["output_tokens"]) == (2, 56)
    assert (
        record_["cache_creation_input_tokens"],
        record_["cache_read_input_tokens"],
    ) == (22869, 0)
    assert record_["cost_usd"] == 0.004602 and record_["turns"] == 1


def test_a_run_with_no_result_line_is_no_result(tmp_path):
    record_ = _failed(tmp_path, GONE, {}, "", False)
    assert record_["reason"] == "no-result"
    assert record_["turns"] is None and record_["input_tokens"] is None
    assert record_["model_ids"] == []


def test_a_failed_check_is_check_failed(tmp_path):
    record_ = _failed(
        tmp_path,
        dict(verify_outcome="failure", job_status="failure", publish_outcome="skipped"),
        fixture_line("result-success.json"),
    )
    assert record_["reason"] == "check-failed" and record_["cost_usd"] == 0.1289566


def test_a_publish_that_found_no_change_is_no_change(tmp_path):
    record_ = _failed(
        tmp_path,
        dict(publish_outcome="failure", job_status="failure"),
        fixture_line("result-success.json"),
        files=("unchanged.md",),
    )
    assert record_["reason"] == "no-change"


def test_any_other_publish_failure_is_publish_failed(tmp_path):
    record_ = _failed(
        tmp_path,
        dict(publish_outcome="failure", job_status="failure"),
        fixture_line("result-success.json"),
    )
    assert record_["reason"] == "publish-failed"


def test_a_cancelled_job_is_cancelled_and_gets_one_plain_line_for_its_record(tmp_path):
    out = built(tmp_path, fixture_line("result-success.json"))
    gh = FakeGitHub([bot_comment(5, "The factory started this Ticket. [Run](x)\n")])
    _last(
        out,
        gh,
        job_status="cancelled",
        agent_outcome="cancelled",
        publish_outcome="skipped",
    )
    record_ = record_of(out)
    assert record_["outcome"] == "fail" and record_["reason"] == "cancelled"
    ((_, body),) = gh.posted
    assert len(body.splitlines()) == 2 and marker_of(body) == record_
    assert "factory:review" not in body


# ---- the last step trusts nothing the agent step wrote ------------------------------


def _forged(tmp_path, numbers):
    out = built(tmp_path, fixture_line("result-success.json"))
    (out / "result.json").write_text(json.dumps(numbers))
    gh = FakeGitHub([bot_comment(6, OPENED)])
    _last(out, gh)
    return record_of(out), gh, out


def test_unknown_fields_are_dropped_and_a_wrong_type_is_null(tmp_path):
    record_, gh, _ = _forged(
        tmp_path,
        {
            "subtype": "success",
            "num_turns": "5",
            "duration_ms": 12.5,
            "total_cost_usd": True,
            "usage": {
                "input_tokens": -3,
                "output_tokens": 7,
                "cache_read_input_tokens": [1],
                "cache_creation_input_tokens": None,
            },
            "issue": 999,
            "pr": 123,
            "repo": "evil/repo",
            "outcome": "fail",
            "extra": "x",
        },
    )
    assert set(record_) == set(marker_of(gh.thread[0]["body"]))
    assert "extra" not in record_ and record_["issue"] == 4 and record_["repo"] == REPO
    assert record_["pr"] == 9 and record_["outcome"] == "ok"
    assert record_["turns"] is None and record_["duration_ms"] is None
    assert record_["cost_usd"] is None and record_["input_tokens"] is None
    assert record_["output_tokens"] == 7 and record_["cache_read_input_tokens"] is None
    assert marker_of(gh.thread[0]["body"]) == record_


def test_a_reason_verdict_or_gate_outside_its_list_is_refused(tmp_path):
    record_ = _failed(
        tmp_path,
        GONE,
        {
            "type": "result",
            "subtype": "error_<script>",
            "verdict": "PASS",
            "gate": "pass",
            "reason": "because",
        },
        "error_<script>",
        False,
    )
    assert record_["reason"] == "no-result"
    assert record_["verdict"] is None and record_["gate"] is None
    for bad in ("because", "error_x-->", "sk-ant-api03-abcdef"):
        got = record.build_record("implement", RunContext(), {}, "fail", bad)
        assert got["reason"] is None
    got = record.build_record(
        "review", RunContext(), {}, "ok", None, verdict="MAYBE", gate="nope"
    )
    assert got["verdict"] is None and got["gate"] is None
    got = record.build_record(
        "review", RunContext(), {}, "ok", None, verdict="BLOCKED", gate="closed"
    )
    assert (got["verdict"], got["gate"]) == ("BLOCKED", "closed")


def test_a_reason_is_a_full_match_and_at_most_48_characters(tmp_path, capsys):
    fits = "error_" + "a" * 42
    for good in (fits, "error_max_budget_usd", "cancelled"):
        assert (
            record.build_record("implement", RunContext(), {}, "fail", good)["reason"]
            == good
        )
    for bad in (fits + "a", "error_max\n", "error_max\n\n", "error_a" + "b" * 500):
        assert (
            record.build_record("implement", RunContext(), {}, "fail", bad)["reason"]
            is None
        )
    assert "reason failed its check" in capsys.readouterr().out


def test_nothing_that_closes_the_comment_or_looks_like_a_token_reaches_the_marker(
    tmp_path,
):
    record_, gh, out = _forged(
        tmp_path,
        {
            "subtype": "success",
            "num_turns": 2,
            "usage": {"input_tokens": 1},
            "model_usage": {"model--> evil": {}, TOKEN: {}, "claude-sonnet-5-5": {}},
        },
    )
    body = gh.thread[0]["body"]
    assert record_["model_ids"] == ["claude-sonnet-5-5"]
    assert body.count("-->") == 1 and body.endswith("-->\n")
    assert "sk-ant-" not in body and "sk-ant-" not in (out / "run.json").read_text()
    record_ = record.build_record(
        "implement", RunContext(repo=TOKEN, project="a-->b"), {}, "ok", None
    )
    assert record_["repo"] is None and record_["project"] is None
    assert "-->" not in json.dumps(record_) and "sk-ant" not in json.dumps(record_)


@pytest.mark.parametrize("poison", ["a-->b", TOKEN])
def test_a_line_that_fails_its_last_check_is_not_posted_and_warns(
    tmp_path, monkeypatch, capsys, poison
):
    """Code review A2: one more check on the whole serialized line, after every field's own."""
    real = record.build_record
    monkeypatch.setattr(
        run_record,
        "build_record",
        lambda *a, **k: dict(real(*a, **k), model_ids=[poison]),
    )
    out = built(tmp_path, fixture_line("result-success.json"))
    gh = FakeGitHub([bot_comment(6, OPENED)])
    assert _last(out, gh) == 0
    assert gh.thread[0]["body"] == OPENED and gh.posted == []
    assert "last check" in capsys.readouterr().out
    assert (out / "run.json").is_file()


def test_the_record_holds_no_transcript_text(tmp_path):
    message = dict(
        fixture_line("result-success.json"),
        result="UNIQUE-MODEL-TEXT",
        errors=["UNIQUE-ERR"],
    )
    out = built(tmp_path, message)
    (out / "summary.md").write_text("UNIQUE-SUMMARY\n")
    (out / "agent.jsonl").write_text('{"text":"UNIQUE-TRANSCRIPT"}\n')
    gh = FakeGitHub([bot_comment(6, OPENED)])
    _last(out, gh)
    for text in (
        (out / "run.json").read_text(),
        gh.thread[0]["body"].split("factory:run ")[1],
    ):
        assert "UNIQUE" not in text
    assert all(
        isinstance(v, (int, float, str, list, type(None)))
        for v in record_of(out).values()
    )


def test_a_file_in_the_output_directory_cannot_choose_the_comment(tmp_path):
    out = built(tmp_path, fixture_line("result-success.json"))
    (out / "context.json").write_text(
        json.dumps({"issue": 1, "comment_id": 5, "pr": 1})
    )
    (out / "comment-id.txt").write_text("5")
    gh = FakeGitHub(
        [
            bot_comment(5, "A human wrote this\n", login="travism26"),
            bot_comment(6, OPENED, login="someone-else[bot]"),
            bot_comment(7, OPENED),
            bot_comment(8, OPENED.replace("pull/9", "pull/10"), login="evil[bot]"),
        ]
    )
    _last(out, gh)
    assert [("factory:run" in c["body"]) for c in gh.thread] == [
        False,
        False,
        True,
        False,
    ]
    assert gh.posted == []


@pytest.mark.parametrize("workflow", ["implement", "rework", "review"])
def test_each_workflow_sets_the_login_in_its_own_last_step(workflow):
    """Code review A5: a step that can write $GITHUB_ENV could change the job's `LOGIN`."""
    text = (WORKFLOWS / f"{workflow}.yml").read_text()
    step = text.split("- name: Leave the run record")[1].split("- name: Keep")[0]
    assert (
        "LOGIN: ${{ vars.FACTORY_CLAUDE_LOGIN || 'subscription' }}"
        in step.split("run: >-")[0]
    )
    assert "secrets." not in step


def test_implement_workflow_runs_the_last_step_after_the_comments_and_before_the_upload():
    text = (WORKFLOWS / "implement.yml").read_text()
    release = text.index("python -m factory.ticket release")
    last = text.index("python -m factory.run_record write --workflow implement")
    upload = text.index("actions/upload-artifact")
    assert release < last < upload
    step = text[text.rindex("      - name:", 0, last) : upload]
    assert "if: always() && steps.build.conclusion != 'skipped'" in step
    assert "secrets." not in step and "CLAUDE_CODE_OAUTH_TOKEN" not in step
    assert "claude" not in step.replace("claude-code-version", "").replace(
        "CLAUDE_CODE_VERSION", ""
    )


def test_the_fixtures_hold_no_token_shaped_string_and_no_identifying_fields():
    for path in FIXTURES.rglob("*"):
        if path.is_file():
            text = path.read_text()
            assert not token_shaped(text), path
    for path in FIXTURES.glob("*.json"):
        text = path.read_text()
        for key in ("session_id", "uuid", "credential_expires_at", '"result":'):
            assert key not in text, (path.name, key)


def test_a_rerun_marks_its_own_comment_once_and_leaves_the_first_attempts(tmp_path):
    out = built(tmp_path, fixture_line("result-success.json"))
    first = '<!-- factory:run {"run_id":777,"attempt":1} -->'
    gh = FakeGitHub([bot_comment(5, FAILED + first + "\n"), bot_comment(9, FAILED)])
    _last(out, gh, attempt="2", publish_outcome="failure", job_status="failure")
    assert gh.thread[0]["body"] == FAILED + first + "\n"
    assert marker_of(gh.thread[1]["body"])["attempt"] == 2


# ---- a wrong-typed `usage` is null, not replaced by `model_usage` (code review A4) ----

MODEL_USAGE = {
    "claude-sonnet-5-5": {
        "inputTokens": 9,
        "outputTokens": 8,
        "cacheCreationInputTokens": 7,
        "cacheReadInputTokens": 6,
    }
}
ZEROS = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
}


@pytest.mark.parametrize(
    "usage",
    [
        "oops",
        [1, 2],
        {**ZEROS, "output_tokens": "0"},
        {**ZEROS, "input_tokens": None},
        {},
    ],
)
def test_a_wrong_typed_usage_is_null_and_is_not_filled_from_model_usage(
    tmp_path, usage, capsys
):
    record_, _, _ = _forged(
        tmp_path,
        {
            "subtype": "success",
            "num_turns": 2,
            "usage": usage,
            "model_usage": MODEL_USAGE,
        },
    )
    wrong = [
        k for k, v in ZEROS.items() if not isinstance(usage, dict) or usage.get(k) != 0
    ]
    for key in wrong:
        assert record_[key] is None, key
    assert "failed its check" in capsys.readouterr().out


def test_an_all_zero_usage_is_filled_from_model_usage(tmp_path):
    record_, _, _ = _forged(
        tmp_path,
        {
            "subtype": "success",
            "num_turns": 2,
            "usage": ZEROS,
            "model_usage": MODEL_USAGE,
        },
    )
    assert (
        record_["input_tokens"],
        record_["output_tokens"],
        record_["cache_creation_input_tokens"],
        record_["cache_read_input_tokens"],
    ) == (9, 8, 7, 6)


# ---- a marker in model text is not a record (code review A1) ------------------------


def test_a_marker_in_the_agent_summary_of_a_no_change_comment_is_not_a_record(tmp_path):
    """The agent's summary is posted in the Ticket's failed comment."""
    forged = (
        '<!-- factory:run {"schema":1,"workflow":"implement","run_id":1,"attempt":1,'
        '"issue":4,"pr":999,"outcome":"ok","cost_usd":9.0} -->'
    )
    out = built(tmp_path, fixture_line("result-success.json"))
    (out / "unchanged.md").write_text("nothing changed\n")
    (out / "summary.md").write_text(f"I did the work.\n{forged}\n")
    gh = FakeGitHub()
    ticket.release(step_args("implement", out), gh)
    assert _last(out, gh, publish_outcome="failure", job_status="failure") == 0
    assert record_of(out)["reason"] == "no-change" and len(gh.thread) == 1
    assert gh.thread[0]["body"].count("<!-- factory:run") == 1
    fixtures = tmp_path / "fx" / "ticket-4"
    fixtures.mkdir(parents=True)
    (fixtures / "issue-comments.json").write_text(
        json.dumps([dict(c, created_at="2026-11-13T10:00:00Z") for c in gh.thread])
    )
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        assert (
            metrics.main(
                ["--fixtures", str(tmp_path / "fx"), "--app-slug", "harness-factory"]
            )
            == 0
        )
    total = [x for x in printed.getvalue().splitlines() if x.startswith("| Total")][0]
    assert "0/1 (0%)" in total and "$9.00" not in total


def test_a_marker_that_is_not_the_final_line_does_not_stop_the_real_one(tmp_path):
    out = built(tmp_path, fixture_line("result-success.json"))
    quoted = OPENED + '<!-- factory:run {"schema":2} --> quoted by someone\n'
    gh = FakeGitHub([bot_comment(6, quoted)])
    _last(out, gh)
    assert gh.thread[0]["body"].startswith(quoted)
    assert json.loads(record.record_text(gh.thread[0]["body"])) == record_of(out)


def test_a_marker_in_the_middle_of_a_comment_is_not_a_record():
    middle = 'text\n<!-- factory:run {"schema":1} -->\nmore text\n'
    assert record.record_text(middle) is None and not record.has_record(middle)
    assert record.record_text('x <!-- factory:run {"schema":1} -->\n') is None
    assert (
        record.record_text('x\n<!-- factory:run {"schema":1} -->\n') == '{"schema":1}'
    )


def test_a_record_that_would_pass_the_comment_limit_is_its_own_one_line_comment(
    tmp_path,
):
    out = built(tmp_path, fixture_line("result-success.json"))
    big = OPENED + "x" * (65536 - len(OPENED) - 10) + "\n"
    gh = FakeGitHub([bot_comment(6, big)])
    assert _last(out, gh) == 0
    assert gh.thread[0]["body"] == big
    ((number, body),) = gh.posted
    assert len(body.splitlines()) == 1 and marker_of(body) == record_of(out)


def _warned(out, name):
    return [
        line
        for line in out.splitlines()
        if line.startswith("::warning title=Run record::")
        and f"the field {name} failed" in line
    ]


def test_a_supplied_issue_that_fails_its_check_is_null_with_a_warning_that_hides_the_value(
    tmp_path, capsys
):
    out = built(tmp_path, fixture_line("result-success.json"))
    gh = FakeGitHub([bot_comment(6, OPENED)])
    assert _last(out, gh, issue=-4242) == 0
    printed = capsys.readouterr().out
    assert record_of(out)["issue"] is None
    assert len(_warned(printed, "issue")) == 1 and "4242" not in printed


def test_an_issue_that_was_never_supplied_is_null_without_a_warning(tmp_path, capsys):
    out = built(tmp_path, fixture_line("result-success.json"))
    gh = FakeGitHub([bot_comment(6, OPENED)])
    assert _last(out, gh, issue=None) == 0
    assert record_of(out)["issue"] is None
    assert _warned(capsys.readouterr().out, "issue") == []
