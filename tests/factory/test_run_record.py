"""Run records (docs/adr/0010-run-records-live-in-comment-markers.md), tested at the
steps' entry points: build saves the raw numbers; run_record.write is the last step."""
import argparse
import json
import re
from pathlib import Path

from factory import run_record, ticket
from factory.claude import Result

FIXTURES = Path(__file__).parent / "fixtures"


def _line(name):
    return json.loads((FIXTURES / name).read_text())


def _built(tmp_path, message, success=True, subtype="success"):
    """Run `ticket.build` with a fake agent that returns `message`, as claude.run would."""
    out = tmp_path / "run-out"
    out.mkdir(exist_ok=True)
    (out / "ticket.md").write_text("# t\n")
    (out / "context.json").write_text(json.dumps({"project": None}))
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)

    def agent(prompt, **kw):
        return Result(success, "MODEL TEXT", subtype, 0.1, message)

    args = argparse.Namespace(out=str(out), work=str(work), login="subscription",
                              model="sonnet", max_budget_usd=5.0)
    try:
        ticket.build(args, run_agent=agent)
    except RuntimeError:
        pass
    return out


def test_build_saves_only_the_numbers_from_the_result_line(tmp_path):
    message = dict(_line("result-success.json"), result="MODEL TEXT secret words")
    out = _built(tmp_path, message)
    saved = json.loads((out / "result.json").read_text())
    assert saved["num_turns"] == 5 and saved["usage"]["cache_read_input_tokens"] == 94606
    assert "MODEL TEXT" not in (out / "result.json").read_text()
    assert "secret words" not in (out / "result.json").read_text()


def test_build_saves_the_numbers_when_the_agent_fails(tmp_path):
    out = _built(tmp_path, _line("result-budget-stop.json"), False, "error_max_budget_usd")
    assert json.loads((out / "result.json").read_text())["subtype"] == "error_max_budget_usd"


# ---- the last step ------------------------------------------------------------

REPO = "travism26/harness-lab"
SHA = "a" * 40
OPENED = f"The factory opened a draft PR: https://github.com/{REPO}/pull/9\n"
RUN_URL = f"https://github.com/{REPO}/actions/runs/777"
FAILED = (f"The factory run for this Ticket failed: [run]({RUN_URL}). `in-progress` has been "
          "removed; re-apply `ready-for-factory` to try again.\n")


class FakeGitHub:
    def __init__(self, comments=()):
        self.thread = list(comments)
        self.posted = []

    def pr_comments(self, repo, number):
        return [dict(c) for c in self.thread]

    def pr(self, repo, number):
        return {"number": number, "headRefOid": SHA}

    def comment(self, repo, number, path):
        self.posted.append((number, path.read_text()))
        self.thread.append({"id": 100 + len(self.posted), "body": path.read_text(),
                            "user": {"login": "harness-factory[bot]"}})
        return 100 + len(self.posted)

    def update_comment(self, repo, comment_id, path):
        for c in self.thread:
            if c["id"] == comment_id:
                c["body"] = path.read_text()


def _bot(id, body, login="harness-factory[bot]"):
    return {"id": id, "body": body, "user": {"login": login}}


def _last(out, gh, **kw):
    base = dict(workflow="implement", out=str(out), repo=REPO, run_id="777", attempt="1",
                issue=4, project="harness", login="subscription", model="sonnet", budget="5",
                claude_code_version="2.1.319", app_slug="harness-factory", run_url=RUN_URL,
                job_status="success", build_outcome="success", verify_outcome="skipped",
                publish_outcome="success")
    base.update(kw)
    return run_record.write(argparse.Namespace(**base), gh)


def _marker(body):
    found = re.findall(r"<!-- factory:run (\{.*?\}) -->", body)
    assert len(found) == 1
    return json.loads(found[0])


def test_an_opened_draft_leaves_a_record_in_a_file_and_on_the_opened_comment(tmp_path):
    out = _built(tmp_path, _line("result-success.json"))
    gh = FakeGitHub([_bot(5, "The factory started this Ticket. [Run](x)\n"), _bot(6, OPENED)])
    assert _last(out, gh) == 0
    record = json.loads((out / "run.json").read_text())
    assert record == _marker(gh.thread[1]["body"])
    assert gh.thread[1]["body"].startswith(OPENED)
    assert "factory:run" not in gh.thread[0]["body"] and gh.posted == []
    assert record["outcome"] == "ok" and record["reason"] is None
    assert record["pr"] == 9 and record["head_sha"] == SHA and record["issue"] == 4
    assert record["model_ids"] == ["claude-sonnet-5-5"]
    assert (record["turns"], record["duration_ms"], record["cost_usd"]) == (5, 40915, 0.1289566)
    assert (record["input_tokens"], record["output_tokens"]) == (10, 4592)
    assert (record["cache_creation_input_tokens"], record["cache_read_input_tokens"]) == (18389, 94606)
    assert record["cost_note"] == "client-estimate" and record["round"] == 0
    assert record["verdict"] is None and record["gate"] is None
    assert record["schema"] == 1 and record["workflow"] == "implement"
    assert record["run_id"] == 777 and record["attempt"] == 1 and record["repo"] == REPO
    assert record["login"] == "subscription" and record["model"] == "sonnet"
    assert record["budget"] == 5 and record["claude_code_version"] == "2.1.319"
    assert record["project"] == "harness" and record["ts"].endswith("Z")
    assert len(record) == 28


def _failed(tmp_path, reason_kw, message=None, subtype="success", success=True, files=()):
    out = _built(tmp_path, message or {}, success, subtype)
    for name in files:
        (out / name).write_text("nothing changed\n")
    gh = FakeGitHub([_bot(5, FAILED)])
    assert _last(out, gh, **reason_kw) == 0
    record = json.loads((out / "run.json").read_text())
    assert record == _marker(gh.thread[0]["body"])
    assert gh.thread[0]["body"].startswith(FAILED) and gh.posted == []
    assert record["outcome"] == "fail" and record["pr"] is None and record["head_sha"] is None
    return record


def test_a_cli_error_subtype_is_the_reason_and_the_budget_stop_tokens_come_from_model_usage(tmp_path):
    record = _failed(tmp_path, dict(build_outcome="failure", job_status="failure",
                                    publish_outcome="skipped"),
                     _line("result-budget-stop.json"), "error_max_budget_usd", False)
    assert record["reason"] == "error_max_budget_usd"
    assert record["model_ids"] == ["claude-haiku-5-5"]
    assert (record["input_tokens"], record["output_tokens"]) == (2, 56)
    assert (record["cache_creation_input_tokens"], record["cache_read_input_tokens"]) == (22869, 0)
    assert record["cost_usd"] == 0.004602 and record["turns"] == 1


def test_a_run_with_no_result_line_is_no_result(tmp_path):
    record = _failed(tmp_path, dict(build_outcome="failure", job_status="failure",
                                    publish_outcome="skipped"), {}, "", False)
    assert record["reason"] == "no-result"
    assert record["turns"] is None and record["input_tokens"] is None and record["model_ids"] == []


def test_a_failed_check_is_check_failed(tmp_path):
    record = _failed(tmp_path, dict(verify_outcome="failure", job_status="failure",
                                    publish_outcome="skipped"), _line("result-success.json"))
    assert record["reason"] == "check-failed" and record["cost_usd"] == 0.1289566


def test_a_publish_that_found_no_change_is_no_change(tmp_path):
    record = _failed(tmp_path, dict(publish_outcome="failure", job_status="failure"),
                     _line("result-success.json"), files=("unchanged.md",))
    assert record["reason"] == "no-change"


def test_any_other_publish_failure_is_publish_failed(tmp_path):
    record = _failed(tmp_path, dict(publish_outcome="failure", job_status="failure"),
                     _line("result-success.json"))
    assert record["reason"] == "publish-failed"


def test_a_cancelled_job_is_cancelled_and_gets_one_plain_line_for_its_record(tmp_path):
    out = _built(tmp_path, _line("result-success.json"))
    gh = FakeGitHub([_bot(5, "The factory started this Ticket. [Run](x)\n")])
    _last(out, gh, job_status="cancelled", build_outcome="cancelled", publish_outcome="skipped")
    record = json.loads((out / "run.json").read_text())
    assert record["outcome"] == "fail" and record["reason"] == "cancelled"
    (_, body), = gh.posted
    assert len(body.splitlines()) == 2 and _marker(body) == record
    assert "factory:review" not in body


# ---- the last step trusts nothing the agent step wrote ------------------------------

def _forged(tmp_path, numbers):
    out = _built(tmp_path, _line("result-success.json"))
    (out / "result.json").write_text(json.dumps(numbers))
    gh = FakeGitHub([_bot(6, OPENED)])
    _last(out, gh)
    return json.loads((out / "run.json").read_text()), gh, out


def test_unknown_fields_are_dropped_and_a_wrong_type_is_null(tmp_path):
    record, gh, _ = _forged(tmp_path, {
        "subtype": "success", "num_turns": "5", "duration_ms": 12.5, "total_cost_usd": True,
        "usage": {"input_tokens": -3, "output_tokens": 7, "cache_read_input_tokens": [1],
                  "cache_creation_input_tokens": None},
        "issue": 999, "pr": 123, "repo": "evil/repo", "outcome": "fail", "extra": "x"})
    assert set(record) == set(json.loads(gh.thread[0]["body"].split("factory:run ")[1][:-5]))
    assert "extra" not in record and record["issue"] == 4 and record["repo"] == REPO
    assert record["pr"] == 9 and record["outcome"] == "ok"
    assert record["turns"] is None and record["duration_ms"] is None
    assert record["cost_usd"] is None and record["input_tokens"] is None
    assert record["output_tokens"] == 7 and record["cache_read_input_tokens"] is None
    assert _marker(gh.thread[0]["body"]) == record


def test_a_reason_verdict_or_gate_outside_its_list_is_refused(tmp_path):
    record = _failed(tmp_path, dict(build_outcome="failure", job_status="failure",
                                    publish_outcome="skipped"),
                     {"type": "result", "subtype": "error_<script>", "verdict": "PASS",
                      "gate": "pass", "reason": "because"}, "error_<script>", False)
    assert record["reason"] == "no-result"
    assert record["verdict"] is None and record["gate"] is None
    for bad in ("because", "error_x-->", "sk-ant-api03-abcdef"):
        got = run_record.build_record("implement", {}, {}, "fail", bad)
        assert got["reason"] is None
    got = run_record.build_record("review", {}, {}, "ok", None, verdict="MAYBE", gate="nope")
    assert got["verdict"] is None and got["gate"] is None
    got = run_record.build_record("review", {}, {}, "ok", None, verdict="BLOCKED", gate="closed")
    assert (got["verdict"], got["gate"]) == ("BLOCKED", "closed")


def test_nothing_that_closes_the_comment_or_looks_like_a_token_reaches_the_marker(tmp_path):
    token = "sk-ant-oat01-" + "x" * 30
    record, gh, out = _forged(tmp_path, {
        "subtype": "success", "num_turns": 2,
        "usage": {"input_tokens": 1},
        "model_usage": {"model--> evil": {}, token: {}, "claude-sonnet-5-5": {}}})
    body = gh.thread[0]["body"]
    assert record["model_ids"] == ["claude-sonnet-5-5"]
    assert body.count("-->") == 1 and body.endswith("-->\n")
    assert "sk-ant-" not in body and "sk-ant-" not in (out / "run.json").read_text()
    record = run_record.build_record("implement", {"repo": token, "project": "a-->b"}, {}, "ok", None)
    assert record["repo"] is None and record["project"] is None
    assert "-->" not in json.dumps(record) and "sk-ant" not in json.dumps(record)


def test_the_record_holds_no_transcript_text(tmp_path):
    message = dict(_line("result-success.json"), result="UNIQUE-MODEL-TEXT", errors=["UNIQUE-ERR"])
    out = _built(tmp_path, message)
    (out / "summary.md").write_text("UNIQUE-SUMMARY\n")
    (out / "agent.jsonl").write_text('{"text":"UNIQUE-TRANSCRIPT"}\n')
    gh = FakeGitHub([_bot(6, OPENED)])
    _last(out, gh)
    for text in ((out / "run.json").read_text(), _marker_text(gh.thread[0]["body"])):
        assert "UNIQUE" not in text
    assert all(isinstance(v, (int, float, str, list, type(None))) for v in
               json.loads((out / "run.json").read_text()).values())


def _marker_text(body):
    return body.split("<!-- factory:run ", 1)[1]


def test_a_file_in_the_output_directory_cannot_choose_the_comment(tmp_path):
    out = _built(tmp_path, _line("result-success.json"))
    (out / "context.json").write_text(json.dumps({"issue": 1, "comment_id": 5, "pr": 1}))
    (out / "comment-id.txt").write_text("5")
    gh = FakeGitHub([_bot(5, "A human wrote this\n", login="travism26"),
                     _bot(6, OPENED, login="someone-else[bot]"),
                     _bot(7, OPENED),
                     _bot(8, OPENED.replace("pull/9", "pull/10"), login="evil[bot]")])
    _last(out, gh)
    assert [("factory:run" in c["body"]) for c in gh.thread] == [False, False, True, False]
    assert gh.posted == []


def test_implement_workflow_runs_the_last_step_after_the_comments_and_before_the_upload():
    text = (Path(__file__).resolve().parents[2] / ".github/workflows/implement.yml").read_text()
    release = text.index("python -m factory.ticket release")
    last = text.index("python -m factory.run_record write --workflow implement")
    upload = text.index("actions/upload-artifact")
    assert release < last < upload
    step = text[text.rindex("      - name:", 0, last):upload]
    assert "if: always() && steps.build.conclusion != 'skipped'" in step
    assert "secrets." not in step and "CLAUDE_CODE_OAUTH_TOKEN" not in step
    assert "claude" not in step.replace("claude-code-version", "").replace("CLAUDE_CODE_VERSION", "")


def test_the_fixtures_hold_no_token_shaped_string_and_no_identifying_fields():
    for path in FIXTURES.glob("*.json"):
        text = path.read_text()
        assert not run_record._UNSAFE_RE.search(text), path.name
        for key in ("session_id", "uuid", "credential_expires_at", '"result":'):
            assert key not in text, (path.name, key)


def test_a_rerun_marks_its_own_comment_once_and_leaves_the_first_attempts(tmp_path):
    out = _built(tmp_path, _line("result-success.json"))
    first = _marker_line = "<!-- factory:run {\"run_id\":777,\"attempt\":1} -->"
    gh = FakeGitHub([_bot(5, FAILED + first + "\n"), _bot(9, FAILED)])
    _last(out, gh, attempt="2", publish_outcome="failure", job_status="failure")
    assert gh.thread[0]["body"] == FAILED + first + "\n"
    assert _marker(gh.thread[1]["body"])["attempt"] == 2
