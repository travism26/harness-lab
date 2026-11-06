import json

import pytest

from factory import claude

STEP_ENV = {
    "PATH": "/usr/bin",
    "GH_TOKEN": "ghs_app_token",
    "GITHUB_TOKEN": "ghs_github_token",
    "ANTHROPIC_API_KEY": "sk-ant-stray",
    "FACTORY_SUBSCRIPTION_TOKEN": "sk-ant-oat-subscription",
    "FACTORY_OPENROUTER_KEY": "sk-or-openrouter",
}


def test_subscription_env_has_only_the_oauth_token():
    env = claude.agent_env("subscription", STEP_ENV)
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat-subscription"
    assert env["PATH"] == "/usr/bin"
    for gone in ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "FACTORY_SUBSCRIPTION_TOKEN",
                 "FACTORY_OPENROUTER_KEY", "ANTHROPIC_BASE_URL"):
        assert gone not in env
    assert "sk-or-openrouter" not in env.values()


def test_openrouter_env_follows_openrouters_claude_code_guide():
    env = claude.agent_env("openrouter", STEP_ENV)
    assert env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-or-openrouter"
    assert env["ANTHROPIC_API_KEY"] == ""
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "anthropic/claude-haiku-5.5"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert "sk-ant-oat-subscription" not in env.values()


@pytest.mark.parametrize("login,var", [("subscription", "FACTORY_SUBSCRIPTION_TOKEN"),
                                       ("openrouter", "FACTORY_OPENROUTER_KEY")])
def test_a_missing_secret_is_a_config_error(login, var):
    env = {k: v for k, v in STEP_ENV.items() if k != var}
    with pytest.raises(claude.ConfigError):
        claude.agent_env(login, env)


def test_command_caps_the_budget_and_binds_denied_tools():
    cmd = claude.command("sonnet", 2, ["Read"], ["Bash", "Read(//proc/**)"], may_edit=False)
    assert cmd[cmd.index("--max-budget-usd") + 1] == "2"
    assert cmd[cmd.index("--disallowedTools") + 1] == "Bash,Read(//proc/**)"
    assert "--permission-mode" not in cmd


@pytest.mark.parametrize("model,budget", [("gpt", 1), ("sonnet", 0)])
def test_command_refuses_bad_model_or_budget(model, budget):
    with pytest.raises(claude.ConfigError):
        claude.command(model, budget, None, [], may_edit=False)


def test_result_message_takes_the_last_result_line():
    lines = ["not json", json.dumps({"type": "assistant"}),
             json.dumps({"type": "result", "subtype": "success", "result": "done"})]
    assert claude.result_message("\n".join(lines))["result"] == "done"


def test_scrub_redacts_secret_values(tmp_path):
    (tmp_path / "agent.jsonl").write_text("token sk-or-openrouter leaked")
    (tmp_path / "clean.md").write_text("nothing here")
    assert claude.scrub(tmp_path, claude.secret_values(STEP_ENV)) == 1
    assert "sk-or-openrouter" not in (tmp_path / "agent.jsonl").read_text()
