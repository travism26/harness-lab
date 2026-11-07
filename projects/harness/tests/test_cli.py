"""Acceptance: the real `harness` command pointed at the stand-in model."""

import json
import subprocess
import sys

import pytest

from harness_lab.cli import main
from harness_lab.standin import StandInModel, error_reply, text_reply, tool_use_reply


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("HARNESS_MAX_TURNS", raising=False)
    monkeypatch.delenv("HARNESS_MODEL", raising=False)
    monkeypatch.setattr("harness_lab.loop.RUNS_DIR", tmp_path / "runs")
    return tmp_path / "runs"


def go(model, *extra):
    return main(["q", "--endpoint", model.endpoint, *extra])


def events(runs):
    files = list(runs.glob("*.jsonl"))
    assert len(files) == 1
    return [json.loads(line) for line in files[0].read_text().splitlines()]


def stop(runs):
    return [e for e in events(runs) if e["event"] == "stop"][0]["stop_reason"]


def test_one_turn_answer(env, capsys):
    with StandInModel([text_reply("42")]) as m:
        assert go(m) == 0
    assert capsys.readouterr().out == "42\n"
    assert stop(env) == "final_answer"
    kinds = [e["event"] for e in events(env)]
    assert kinds == ["run_start", "request", "reply", "usage", "stop"]
    assert events(env)[0]["question"] == "q"
    assert events(env)[2]["content"] == [{"type": "text", "text": "42"}]
    assert events(env)[-1]["stop_reason"] == "final_answer"


def test_tool_call_run(env, capsys):
    replies = [tool_use_reply("read_file", {"path": "hello.txt"}), text_reply("done")]
    with StandInModel(replies) as m:
        assert go(m) == 0
    assert capsys.readouterr().out == "done\n"
    result = m.requests[1]["body"]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_standin"
    assert result["content"]
    kinds = [e["event"] for e in events(env)]
    assert kinds.count("request") == 2
    call = [e for e in events(env) if e["event"] == "tool_call"][0]
    assert call["name"] == "read_file" and call["input"] == {"path": "hello.txt"}
    res = [e for e in events(env) if e["event"] == "tool_result"][0]
    assert res["output"] == result["content"] and res["refused"] is False


def test_refused_path(env, capsys):
    with StandInModel([tool_use_reply("read_file", {"path": "../pyproject.toml"}), text_reply("no")]) as m:
        assert go(m) == 1
    assert "refused" in capsys.readouterr().err
    assert stop(env) == "refused_tool_call"
    assert len(m.requests) == 1
    refused = [e for e in events(env) if e["event"] == "tool_result"][0]
    assert refused["refused"] is True and "outside the workspace" in refused["output"]
    call = [e for e in events(env) if e["event"] == "tool_call"][0]
    assert call["input"] == {"path": "../pyproject.toml"}


def test_turn_cap(env, capsys):
    replies = [tool_use_reply("read_file", {"path": "hello.txt"}) for _ in range(5)]
    with StandInModel(replies) as m:
        assert go(m, "--max-turns", "2") == 1
    assert len(m.requests) == 2
    assert stop(env) == "turn_cap"


def test_turn_cap_from_env(env, monkeypatch):
    monkeypatch.setenv("HARNESS_MAX_TURNS", "1")
    with StandInModel([tool_use_reply("read_file", {"path": "hello.txt"})] * 3) as m:
        assert go(m) == 1
    assert len(m.requests) == 1


@pytest.mark.parametrize("turns", ["0", "-3"])
def test_turn_cap_below_one_rejected_from_flag(env, capsys, turns):
    with StandInModel([text_reply("x")]) as m:
        assert go(m, "--max-turns", turns) == 1
    assert "--max-turns must be at least 1" in capsys.readouterr().err
    assert m.requests == []


@pytest.mark.parametrize("turns", ["0", "-3"])
def test_turn_cap_below_one_rejected_from_env(env, monkeypatch, capsys, turns):
    monkeypatch.setenv("HARNESS_MAX_TURNS", turns)
    with StandInModel([text_reply("x")]) as m:
        assert go(m) == 1
    assert "HARNESS_MAX_TURNS must be at least 1" in capsys.readouterr().err
    assert m.requests == []


def test_unresolvable_path_is_an_error_not_a_refusal(env, capsys):
    replies = [tool_use_reply("read_file", {"path": "a\x00b"}), text_reply("recovered")]
    with StandInModel(replies) as m:
        assert go(m) == 0
    assert capsys.readouterr().out == "recovered\n"
    assert stop(env) == "final_answer"
    result = m.requests[1]["body"]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "cannot resolve path" in result["content"]
    res = [e for e in events(env) if e["event"] == "tool_result"][0]
    assert res["refused"] is False


def sent_model(*extra):
    with StandInModel([text_reply("x")]) as m:
        assert go(m, *extra) == 0
    return m.requests[0]["body"]["model"]


def test_model_flag_shortcut_expands(env):
    assert sent_model("--model", "deepseek") == "deepseek/deepseek-v4-flash"


def test_model_flag_full_name_passes_through(env):
    assert sent_model("--model", "some/full-name") == "some/full-name"


def test_model_flag_beats_env(env, monkeypatch):
    monkeypatch.setenv("HARNESS_MODEL", "opus")
    assert sent_model("--model", "sonnet") == "anthropic/claude-sonnet-5.5"


def test_provider_error(env, capsys):
    with StandInModel([error_reply(403, "Key limit exceeded")]) as m:
        assert go(m) == 1
    assert "Key limit exceeded" in capsys.readouterr().err
    assert stop(env) == "provider_error"
    evs = events(env)
    assert "Key limit exceeded" in [e for e in evs if e["event"] == "provider_error"][0]["error"]
    assert "Key limit exceeded" in evs[-1]["error"]


def test_missing_key(env, monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert main(["q", "--endpoint", "http://127.0.0.1:1/v1/messages"]) == 1
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err


def test_cost_logged_only_when_reported(env):
    reply = text_reply("x")
    reply["usage"] = {"input_tokens": 5, "output_tokens": 7, "cost": 0.0012}
    with StandInModel([reply]) as m:
        go(m)
    usage = [e for e in events(env) if e["event"] == "usage"][0]
    assert usage["cost"] == 0.0012 and usage["input_tokens"] == 5


def test_no_cost_when_not_reported(env):
    with StandInModel([text_reply("x")]) as m:
        go(m)
    assert "cost" not in [e for e in events(env) if e["event"] == "usage"][0]


def test_module_runs_with_help():
    out = subprocess.run([sys.executable, "-m", "harness_lab.cli", "--help"], capture_output=True, text=True)
    assert out.returncode == 0 and "question" in out.stdout
