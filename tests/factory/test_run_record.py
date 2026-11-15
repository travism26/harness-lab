"""Run records (docs/adr/0010-run-records-live-in-comment-markers.md), tested at the
steps' entry points: build saves the raw numbers; run_record.write is the last step."""
import argparse
import json
from pathlib import Path

from factory import ticket
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
