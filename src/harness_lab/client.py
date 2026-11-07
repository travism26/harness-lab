"""Model client: plain HTTP to OpenRouter's Anthropic-format Messages endpoint.

No Anthropic SDK. The endpoint address, key and model are inputs; the key
comes only from the environment (see docs/adr/0002).
"""

import json
import os
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/messages"
KEY_VAR = "OPENROUTER_API_KEY"
MODEL_VAR = "HARNESS_MODEL"
DEFAULT_MODEL = "haiku"

SHORTCUTS = {
    "haiku": "anthropic/claude-haiku-5.5",
    "sonnet": "anthropic/claude-sonnet-5.5",
    "opus": "anthropic/claude-opus-5.5",
    "deepseek": "deepseek/deepseek-v4-flash",
}


class ModelError(Exception):
    """A readable error from the model client."""


def resolve_model(model: str | None = None, env=None) -> str:
    """`--model`, else HARNESS_MODEL, else Haiku. Shortcuts expand; other values pass through."""
    env = os.environ if env is None else env
    choice = model or env.get(MODEL_VAR) or DEFAULT_MODEL
    return SHORTCUTS.get(choice, choice)


def read_key(env=None) -> str:
    env = os.environ if env is None else env
    key = env.get(KEY_VAR)
    if not key:
        raise ModelError(f"{KEY_VAR} is not set. Export your OpenRouter key before running the harness.")
    return key


def _provider_message(body: bytes) -> str:
    try:
        data = json.loads(body)
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err)
        if err:
            return str(err)
    except (ValueError, AttributeError):
        pass
    return body.decode("utf-8", "replace").strip()[:200]


class ModelClient:
    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, model: str | None = None,
                 api_key: str | None = None, env=None, timeout: float = 60):
        self.endpoint = endpoint
        self.model = resolve_model(model, env)
        self.api_key = api_key if api_key is not None else read_key(env)
        self.timeout = timeout

    def send(self, messages: list, max_tokens: int = 1024, system: str | None = None,
             tools: list | None = None) -> dict:
        """Post one Messages request and return the parsed reply."""
        payload = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = tools
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode(),
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key}",
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as e:
            detail = _provider_message(e.read())
            raise ModelError(f"Model provider returned HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise ModelError(f"Could not reach the model endpoint {self.endpoint}: {e.reason}") from None
        except ValueError:
            raise ModelError("Model provider returned a reply that is not JSON") from None
