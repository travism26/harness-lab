# Episode 1: a minimal loop

Episode notes: source material for the post, which is written separately in
[travism26/blog](https://github.com/travism26/blog). Facts only. No productivity figures.

## What was built

The harness can now run a model in a tool loop: it sends a question, runs the model's `read_file` Tool calls against a workspace folder, sends back the Tool results, and repeats until a final answer. Every Run writes a Run log.

- Plain HTTP client for OpenRouter's Anthropic-format Messages endpoint, with no SDK ([ADR 0009](../adr/0009-plain-http-in-anthropics-format-not-the-python-sdk.md)).
- Model choice: Haiku by default; shortcuts `haiku`, `sonnet`, `opus`, `deepseek`; any other OpenRouter model name passes through.
- One tool, `read_file`, confined to `projects/harness/workspace/`. A path outside it is refused and stops the Run.
- A turn cap (default 10), and a Run log in JSON lines under `projects/harness/runs/`.

## Tickets and PRs

| Ticket | PR | Rework rounds | Outcome |
|---|---|---|---|
| <https://github.com/travism26/harness-lab/issues/7> | <https://github.com/travism26/harness-lab/pull/11> | not recorded in the Ticket | merged before the live Run |
| <https://github.com/travism26/harness-lab/issues/8> | <https://github.com/travism26/harness-lab/pull/23> | not recorded in the Ticket | merged before the live Run |
| <https://github.com/travism26/harness-lab/issues/9> | <https://github.com/travism26/harness-lab/pull/24> | 2 | went to `ready-for-human`; the owner finished it by hand, then merged |
| <https://github.com/travism26/harness-lab/issues/10> | this PR | not recorded | open |

## What broke

- PR #24 (ticket 3) went to `ready-for-human` after 2 rework rounds. The owner fixed three things by hand (see the owner's comment on #24): the turn-cap check, the result for an unresolvable path, and the missing `--model` flag.
- The refusal path does not match Spec #6 story 5. A refused `read_file` call ends the Run with stop reason `refused_tool_call`, so the model never sees the refused Tool result. The refusal is recorded in the Run log but not sent back to the model. Spec #6 story 5 reads as "reported back to the model as a Tool result".

## Key snippets

The loop (`projects/harness/src/harness_lab/loop.py`): a reply with no `tool_use` block is the final answer; otherwise each call is run and its result goes back as a `tool_result` block.

```python
calls = [b for b in content if b.get("type") == "tool_use"]
if not calls:
    return RunResult(FINAL_ANSWER, answer=_text(content))
...
results.append({"type": "tool_result", "tool_use_id": call.get("id"),
                "content": outcome.output})
```

Model shortcuts (`projects/harness/src/harness_lab/client.py`):

```python
SHORTCUTS = {
    "haiku": "anthropic/claude-haiku-5.5",
    "sonnet": "anthropic/claude-sonnet-5.5",
    "opus": "anthropic/claude-opus-5.5",
    "deepseek": "deepseek/deepseek-v4-flash",
}
```

Permalinks (URLs with a commit SHA): the live Run was made on `main` at `bd9f7a3`, so the snippets above can be read at that commit, e.g. <https://github.com/travism26/harness-lab/blob/bd9f7a3/projects/harness/src/harness_lab/loop.py> and <https://github.com/travism26/harness-lab/blob/bd9f7a3/projects/harness/src/harness_lab/client.py>.

## Live Run

The owner's live Run on 2026-11-07, with the `harness-lab-local` key, `main` at `bd9f7a3`. The owner checked all three Run logs for the key (`sk-or`), `Authorization`, `Bearer` and `api_key`: none appear.

### 1. Haiku (default)

`uv run harness "What does the file hello.txt in the workspace say?"`

```
The file hello.txt says:

"This is a sample file in the harness workspace.
The read_file tool can read it."
```

Exit 0. Run log `run-20261107T110701.jsonl`. Stop reason `final_answer`. Model `anthropic/claude-haiku-5.5`.

| Turn | Reply stop reason | Tool call | Input / output tokens | Cost (reported by OpenRouter) |
|---|---|---|---|---|
| 1 | `tool_use` | `read_file {"path": "hello.txt"}`, id `toolu_01TW…`, refused: false | 410 / 51 | $0.0000665 |
| 2 | `end_turn` | none | 492 / 38 | $0.0000682 |

### 2. DeepSeek

`uv run harness --model deepseek "What does the file hello.txt in the workspace say?"`

```
The file `hello.txt` in the workspace says:

> This is a sample file in the harness workspace.
> The read_file tool can read it.
```

Exit 0. Run log `run-20261107T110717.jsonl`. Stop reason `final_answer`. Model `deepseek/deepseek-v4-flash`.

| Turn | Reply stop reason | Tool call | Input / output tokens | Cost (reported by OpenRouter) |
|---|---|---|---|---|
| 1 | `tool_use` | `read_file {"path": "hello.txt"}`, id `call_5819…`, refused: false | 310 / 45 | $0.00019365 |
| 2 | `end_turn` | none | 380 / 41 | $0.00006468 |

### 3. Refusal

`uv run harness "Read ../README.md"`

```
harness: refused tool call: Error: '../README.md' is outside the workspace and was refused.
harness: run log: projects/harness/runs/run-20261107T110730.jsonl
```

Non-zero exit. In Turn 1, Haiku asked for `read_file {"path": "../README.md"}`. The Tool result was refused (`refused: true`) and the Run stopped with stop reason `refused_tool_call`. Turn 1 used 401 input / 50 output tokens and cost $0.0000651.

### Tool calls in Anthropic's format

- **Haiku:** asked for `read_file {"path": "hello.txt"}` as a `tool_use` block (reply stop reason `tool_use`, id `toolu_…`). After the Tool result went back it answered with `end_turn`. The refusal Run showed the same `tool_use` shape for a path outside the workspace.
- **DeepSeek:** the same round trip worked unchanged: a `tool_use` call for `read_file {"path": "hello.txt"}`, then `end_turn` with the answer. Its tool-use ids are OpenAI-style `call_…`, not `toolu_…`.
- **Did OpenRouter's Messages endpoint accept DeepSeek?** Yes. Both the tool definition and the `tool_use`/`tool_result` round trip worked in Anthropic's format, with no changes.

## Cost

Only the figures OpenRouter reported in the Run logs; none estimated.

- Haiku: $0.0000665 (Turn 1) and $0.0000682 (Turn 2).
- DeepSeek: $0.00019365 (Turn 1, about 3x Haiku's first Turn) and $0.00006468 (Turn 2, cheaper than Haiku's). It used fewer tokens on both Turns.
- Refusal Run, Turn 1: $0.0000651.

## Open questions for the post

- Should the Run continue after a refused Tool call, with the refusal sent back to the model as a Tool result? Spec #6 story 5 reads that way; the harness currently stops. Left for a later episode.
