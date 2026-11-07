"""The loop: send the question, run read_file tool calls, repeat until a final answer.

Every Run writes one JSON-lines file under projects/harness/runs/ (gitignored).
"""

import json
import os
import time
from pathlib import Path

from harness_lab.client import ModelError
from harness_lab.tools import TOOLS, WORKSPACE, is_refused, read_file

DEFAULT_MAX_TURNS = 10
MAX_TURNS_VAR = "HARNESS_MAX_TURNS"
# projects/harness/runs/
RUNS_DIR = Path(__file__).resolve().parents[2] / "runs"

FINAL_ANSWER = "final_answer"
TURN_CAP = "turn_cap"
PROVIDER_ERROR = "provider_error"
REFUSED_TOOL_CALL = "refused_tool_call"


def resolve_max_turns(value: int | None = None, env=None) -> int:
    """`--max-turns`, else HARNESS_MAX_TURNS, else 10."""
    env = os.environ if env is None else env
    if value is not None:
        return value
    raw = env.get(MAX_TURNS_VAR)
    if not raw:
        return DEFAULT_MAX_TURNS
    try:
        turns = int(raw)
    except ValueError:
        raise ModelError(f"{MAX_TURNS_VAR} must be a whole number, got {raw!r}") from None
    if turns < 1:
        raise ModelError(f"{MAX_TURNS_VAR} must be at least 1, got {turns}")
    return turns


class RunLog:
    """One JSON-lines file for one Run."""

    def __init__(self, runs_dir: Path = RUNS_DIR):
        runs_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%S")
        n = 0
        while True:
            path = runs_dir / f"run-{stamp}{f'-{n}' if n else ''}.jsonl"
            try:
                self._file = open(path, "x", encoding="utf-8")
                break
            except FileExistsError:
                n += 1
        self.path = path

    def event(self, kind: str, **data) -> None:
        self._file.write(json.dumps({"time": time.time(), "event": kind, **data}) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class RunResult:
    def __init__(self, stop_reason: str, answer: str | None = None, error: str | None = None,
                 log_path: Path | None = None):
        self.stop_reason = stop_reason
        self.answer = answer
        self.error = error
        self.log_path = log_path

    @property
    def ok(self) -> bool:
        return self.stop_reason == FINAL_ANSWER


def _text(content: list) -> str:
    return "".join(b.get("text", "") for b in content if b.get("type") == "text")


def run(question: str, client, max_turns: int = DEFAULT_MAX_TURNS, runs_dir: Path | None = None,
        workspace: Path = WORKSPACE) -> RunResult:
    log = RunLog(runs_dir or RUNS_DIR)
    try:
        log.event("run_start", question=question, model=client.model, max_turns=max_turns)
        result = _loop(question, client, max_turns, log, workspace)
        log.event("stop", stop_reason=result.stop_reason,
                  **({"error": result.error} if result.error else {}))
        result.log_path = log.path
        return result
    finally:
        log.close()


def _loop(question, client, max_turns, log, workspace) -> RunResult:
    messages = [{"role": "user", "content": question}]
    for turn in range(1, max_turns + 1):
        log.event("request", turn=turn, messages=messages)
        try:
            reply = client.send(messages, tools=TOOLS)
        except ModelError as err:
            return RunResult(PROVIDER_ERROR, error=str(err))
        content = reply.get("content") or []
        log.event("reply", turn=turn, content=content, reply_stop_reason=reply.get("stop_reason"))
        usage = reply.get("usage") or {}
        usage_event = {k: usage[k] for k in ("input_tokens", "output_tokens") if k in usage}
        # Cost only when OpenRouter reports it; never estimated.
        if usage.get("cost") is not None:
            usage_event["cost"] = usage["cost"]
        log.event("usage", turn=turn, **usage_event)

        calls = [b for b in content if b.get("type") == "tool_use"]
        if not calls:
            return RunResult(FINAL_ANSWER, answer=_text(content))

        messages.append({"role": "assistant", "content": content})
        results = []
        for call in calls:
            name, args = call.get("name"), call.get("input") or {}
            log.event("tool_call", turn=turn, id=call.get("id"), name=name, input=args)
            if name != "read_file" or not isinstance(args.get("path"), str):
                output = f"Error: unknown tool or bad input for {name!r}"
                refused = False
            else:
                refused = is_refused(args["path"], workspace)
                output = read_file(args["path"], workspace)
            log.event("tool_result", turn=turn, id=call.get("id"), output=output, refused=refused)
            if refused:
                return RunResult(REFUSED_TOOL_CALL, error=output)
            results.append({"type": "tool_result", "tool_use_id": call.get("id"), "content": output,
                            **({"is_error": True} if output.startswith("Error:") else {})})
        messages.append({"role": "user", "content": results})
    return RunResult(TURN_CAP, error=f"Stopped at the turn cap of {max_turns} without a final answer.")
