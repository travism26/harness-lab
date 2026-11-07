import pytest

from harness_lab.client import ModelClient, ModelError, resolve_model
from harness_lab.standin import StandInModel, error_reply, text_reply, tool_use_reply

MSG = [{"role": "user", "content": "hi"}]


def test_text_reply():
    with StandInModel([text_reply("hello")]) as m:
        reply = ModelClient(m.endpoint, api_key="k").send(MSG)
    assert reply["content"][0]["text"] == "hello"
    req = m.requests[0]
    assert req["body"]["messages"] == MSG
    assert req["headers"]["authorization"] == "Bearer k"


def test_tool_use_reply():
    tools = [{"name": "run", "description": "d", "input_schema": {"type": "object"}}]
    with StandInModel([tool_use_reply("run", {"cmd": "ls"})]) as m:
        reply = ModelClient(m.endpoint, api_key="k").send(MSG, tools=tools)
    block = reply["content"][0]
    assert (block["type"], block["name"], block["input"]) == ("tool_use", "run", {"cmd": "ls"})
    assert m.requests[0]["body"]["tools"] == tools


@pytest.mark.parametrize("status,message", [
    (401, "No auth credentials found"), (429, "Rate limit exceeded"), (403, "Key limit exceeded")])
def test_provider_error_is_readable(status, message):
    with StandInModel([error_reply(status, message)]) as m:
        with pytest.raises(ModelError) as e:
            ModelClient(m.endpoint, api_key="k").send(MSG)
    assert str(status) in str(e.value) and message in str(e.value)


def test_missing_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ModelError, match="OPENROUTER_API_KEY"):
        ModelClient("http://127.0.0.1:1/v1/messages")


def test_key_from_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "envkey")
    with StandInModel([text_reply("x")]) as m:
        ModelClient(m.endpoint).send(MSG)
    assert m.requests[0]["headers"]["authorization"] == "Bearer envkey"


@pytest.mark.parametrize("name,full", [
    ("haiku", "anthropic/claude-haiku-5.5"),
    ("sonnet", "anthropic/claude-sonnet-5.5"),
    ("opus", "anthropic/claude-opus-5.5"),
    ("deepseek", "deepseek/deepseek-v4-flash")])
def test_shortcuts(name, full):
    assert resolve_model(name, env={}) == full


def test_full_name_passes_through():
    assert resolve_model("acme/some-model", env={}) == "acme/some-model"


def test_env_fallback_and_precedence():
    assert resolve_model(None, env={"HARNESS_MODEL": "sonnet"}) == "anthropic/claude-sonnet-5.5"
    assert resolve_model("opus", env={"HARNESS_MODEL": "sonnet"}) == "anthropic/claude-opus-5.5"
    assert resolve_model(None, env={}) == "anthropic/claude-haiku-5.5"


def test_model_sent_in_request():
    with StandInModel([text_reply("x")]) as m:
        ModelClient(m.endpoint, model="deepseek", api_key="k").send(MSG)
    assert m.requests[0]["body"]["model"] == "deepseek/deepseek-v4-flash"
