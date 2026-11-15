"""The metrics report (docs/factory/README.md, "Metrics report"), tested at its entry point:
a fixtures directory in, a markdown table and an exit code out."""
import json
import re
from pathlib import Path


from factory import metrics

FIXTURES = Path(__file__).parent / "fixtures" / "metrics"
BOT = "travism26-factory[bot]"


def _run(capsys, *argv):
    code = metrics.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _record(**kw):
    base = {"schema": 1, "ts": "2026-11-13T10:00:00Z", "workflow": "implement", "run_id": 1,
            "attempt": 1, "repo": "o/r", "issue": 5, "pr": None, "login": "subscription",
            "outcome": "ok", "reason": None, "verdict": None, "cost_usd": 0.5,
            "duration_ms": 60000}
    base.update(kw)
    return base


def _marker(record):
    return "<!-- factory:run " + json.dumps(record) + " -->"


def _comment(id, body, login=BOT):
    return {"id": id, "user": {"login": login}, "created_at": "2026-11-13T10:00:00Z", "body": body}


def _fixtures(tmp_path, *comments):
    """A one-Ticket fixtures directory holding `comments`."""
    d = tmp_path / "fx" / "ticket-5"
    d.mkdir(parents=True)
    (d / "issue-comments.json").write_text(json.dumps(list(comments)))
    return tmp_path / "fx"


def test_the_golden_table_comes_from_the_fixtures_offline(capsys):
    code, out, err = _run(capsys, "--fixtures", str(FIXTURES),
                          "--backfill", str(FIXTURES / "backfill.jsonl"))
    assert code == 0, err
    assert out == (FIXTURES / "golden.md").read_text()


def test_a_marker_on_a_comment_the_bot_did_not_write_is_ignored(tmp_path, capsys):
    fx = _fixtures(tmp_path,
                   _comment(1, "opened\n" + _marker(_record(pr=9, cost_usd=0.5))),
                   _comment(2, _marker(_record(run_id=2, cost_usd=99.0)), login="travism26"))
    code, out, _ = _run(capsys, "--fixtures", str(fx))
    assert code == 0
    assert "$0.50" in out
    assert "99" not in out


def test_two_attempts_of_one_run_both_count_toward_cost(tmp_path, capsys):
    fx = _fixtures(tmp_path,
                   _comment(1, _marker(_record(attempt=1, cost_usd=0.5, outcome="fail"))),
                   _comment(2, _marker(_record(attempt=2, cost_usd=0.25, pr=9))),
                   _comment(3, _marker(_record(attempt=2, cost_usd=0.25, pr=9))))
    code, out, _ = _run(capsys, "--fixtures", str(fx))
    assert code == 0
    assert "$0.75" in out


def test_a_record_with_an_unknown_schema_is_refused(tmp_path, capsys):
    fx = _fixtures(tmp_path, _comment(1, _marker(_record(schema=2))))
    code, out, err = _run(capsys, "--fixtures", str(fx))
    assert code == 1
    assert out == ""
    assert "schema 2" in err


def test_a_fixture_holding_a_token_shaped_string_is_rejected(tmp_path, capsys):
    fx = _fixtures(tmp_path, _comment(1, "opened\n" + _marker(_record(pr=9)) + "\nsk-ant-api03-abc123"))
    code, out, err = _run(capsys, "--fixtures", str(fx))
    assert code == 1
    assert out == ""
    assert "token" in err
    assert "abc123" not in err


def test_no_committed_fixture_holds_a_token_shaped_string():
    pattern = re.compile(r"sk-ant-|sk-or-|\bgh[pousr]_[A-Za-z0-9]|github_pat_|xox[abposr]-|eyJ[A-Za-z0-9_-]{10,}")
    for path in FIXTURES.rglob("*"):
        if path.is_file():
            assert not pattern.search(path.read_text()), path


def test_a_ticket_with_no_draft_lowers_the_draft_rate(tmp_path, capsys):
    fx = _fixtures(tmp_path,
                   _comment(1, "opened\n" + _marker(_record(pr=9))),
                   _comment(2, "failed\n" + _marker(_record(issue=6, run_id=2, outcome="fail"))))
    code, out, _ = _run(capsys, "--fixtures", str(fx))
    assert code == 0
    total = [line for line in out.splitlines() if line.startswith("| Total")][0]
    assert "1/2 (50%)" in total


def test_the_first_review_decides_first_pass(tmp_path, capsys):
    fx = _fixtures(tmp_path,
                   _comment(1, "opened\n" + _marker(_record(pr=9))),
                   _comment(2, _marker(_record(workflow="review", run_id=3, pr=9, verdict="BLOCKED",
                                               ts="2026-11-13T11:00:00Z"))),
                   _comment(3, _marker(_record(workflow="review", run_id=2, pr=9, verdict="PASS",
                                               ts="2026-11-13T12:00:00Z"))))
    code, out, _ = _run(capsys, "--fixtures", str(fx))
    assert code == 0
    total = [line for line in out.splitlines() if line.startswith("| Total")][0]
    assert "0/1 (0%)" in total


def test_a_missing_source_is_an_error(tmp_path, capsys):
    code, out, err = _run(capsys, "--fixtures", str(tmp_path / "nope"))
    assert code == 1
    assert out == ""
    assert err
