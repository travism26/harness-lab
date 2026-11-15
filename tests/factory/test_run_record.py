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
