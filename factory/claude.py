"""Run Claude Code headless for a factory step, on the login the switch rule allows.

The workflow hands the step two secrets under factory names:

  FACTORY_SUBSCRIPTION_TOKEN  the owner's `claude setup-token` token
  FACTORY_OPENROUTER_KEY      the OpenRouter key for GitHub runs

agent_env() builds the agent's environment from the step's: it drops every
credential, then sets only the ones the chosen login needs, in the variable
names Claude Code reads. The agent never sees a GitHub token or the secret it
is not using.
"""

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional

from factory.switch_rule import OPENROUTER, SUBSCRIPTION

OPENROUTER_BASE_URL = "https://openrouter.ai/api"
# Claude Code's model aliases, mapped to OpenRouter's model ids
# (https://openrouter.ai/docs/guides/coding-agents/claude-code-integration).
OPENROUTER_MODELS = {
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "anthropic/claude-opus-5.5",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "anthropic/claude-sonnet-5.5",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "anthropic/claude-haiku-5.5",
}
MODELS = ("haiku", "sonnet", "opus")
SECRET_VARS = ("FACTORY_SUBSCRIPTION_TOKEN", "FACTORY_OPENROUTER_KEY")
# Never passed to the agent, whatever the login.
_DROPPED = ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
            "ACTIONS_ID_TOKEN_REQUEST_URL", "CLAUDE_CODE_OAUTH_TOKEN") + SECRET_VARS


class ConfigError(RuntimeError):
    """The step lacks the secret its login needs."""


def agent_env(login: str, step_env: Mapping[str, str]) -> dict:
    env = {k: v for k, v in step_env.items()
           if k not in _DROPPED and not k.startswith("ANTHROPIC_")}
    if login == SUBSCRIPTION:
        token = step_env.get("FACTORY_SUBSCRIPTION_TOKEN") or ""
        if not token:
            raise ConfigError("the login is subscription but the repository secret "
                              "CLAUDE_CODE_OAUTH_TOKEN is empty")
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    elif login == OPENROUTER:
        key = step_env.get("FACTORY_OPENROUTER_KEY") or ""
        if not key:
            raise ConfigError("the login is openrouter but the repository secret "
                              "OPENROUTER_API_KEY is empty")
        env["ANTHROPIC_BASE_URL"] = OPENROUTER_BASE_URL
        env["ANTHROPIC_AUTH_TOKEN"] = key
        # OpenRouter's guide: must be explicitly empty, or Claude Code uses it.
        env["ANTHROPIC_API_KEY"] = ""
        env.update(OPENROUTER_MODELS)
    else:
        raise ConfigError(f"unknown login {login!r}")
    return env


def secret_values(step_env: Mapping[str, str]) -> List[str]:
    return [step_env[k] for k in SECRET_VARS if len(step_env.get(k) or "") >= 8]


def scrub(out: Path, secrets: List[str]) -> int:
    """Blank every secret value out of the files under out, before anything
    is posted or uploaded. Returns how many files changed."""
    changed = 0
    for f in (p for p in out.rglob("*") if p.is_file()):
        text = f.read_text(errors="replace")
        clean = text
        for s in secrets:
            clean = clean.replace(s, "[REDACTED]")
        if clean != text:
            f.write_text(clean)
            changed += 1
    return changed


@dataclass(frozen=True)
class Result:
    success: bool
    text: str
    subtype: str = ""
    cost_usd: float = 0.0


def command(model: str, max_budget_usd: float, allowed_tools: Optional[List[str]],
            disallowed_tools: List[str], may_edit: bool) -> List[str]:
    if model not in MODELS:
        raise ConfigError(f"model must be one of {', '.join(MODELS)}, got {model!r}")
    if max_budget_usd <= 0:
        raise ConfigError("the budget cap must be positive")
    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose",
           "--model", model, "--max-budget-usd", f"{max_budget_usd:g}",
           "--setting-sources", "project"]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools)]
    if disallowed_tools:
        cmd += ["--disallowedTools", ",".join(disallowed_tools)]
    if may_edit:
        # Unattended: nobody is there to answer a permission prompt. The
        # disallowed tools still bind, and the agent holds no GitHub token.
        cmd += ["--permission-mode", "bypassPermissions"]
    return cmd


def result_message(transcript_text: str) -> dict:
    """The CLI's closing `result` message from a stream-json transcript, or {}."""
    result = {}
    for line in transcript_text.splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get("type") == "result":
            result = msg
    return result


def run(prompt: str, login: str, model: str, max_budget_usd: float, cwd: str,
        transcript: Path, disallowed_tools: List[str],
        allowed_tools: Optional[List[str]] = None, may_edit: bool = False,
        step_env: Optional[Mapping[str, str]] = None) -> Result:
    step_env = os.environ if step_env is None else step_env
    env = agent_env(login, step_env)
    cmd = command(model, max_budget_usd, allowed_tools, disallowed_tools, may_edit)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    with transcript.open("w") as out:
        proc = subprocess.run(cmd, input=prompt, stdout=out, stderr=subprocess.PIPE,
                              text=True, cwd=cwd, env=env)
    msg = result_message(transcript.read_text(errors="replace"))
    ok = proc.returncode == 0 and msg.get("subtype") == "success" and not msg.get("is_error")
    text = msg.get("result") or proc.stderr.strip() or f"claude exited {proc.returncode}"
    return Result(ok, text, msg.get("subtype", ""), float(msg.get("total_cost_usd") or 0))


def failure_message(result: Result, max_budget_usd: float, budget_var: str) -> str:
    if result.subtype == "error_max_budget_usd":
        return (f"the agent stopped at its budget cap (${max_budget_usd:g}, spent "
                f"${result.cost_usd:.2f}); raise {budget_var} if the work needs more")
    return f"the agent failed ({result.subtype or 'no result'}): {result.text[:500]}"
