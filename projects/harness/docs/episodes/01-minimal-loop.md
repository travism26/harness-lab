# Episode 1: a minimal loop

Episode notes: source material for the post, which is written separately in
[travism26/blog](https://github.com/travism26/blog). Facts only. No productivity figures.

## What was built

The harness can now run a model in a tool loop: it sends a question, runs the model's `read_file` Tool calls against a workspace folder, sends back the Tool results, and repeats until a final answer. Every Run writes a Run log.

- Plain HTTP client for OpenRouter's Anthropic-format Messages endpoint, with no SDK ([ADR 0009](adr/0009-plain-http-in-anthropics-format-not-the-python-sdk.md)).
- Model choice: Haiku by default; shortcuts `haiku`, `sonnet`, `opus`, `deepseek`; any other OpenRouter model name passes through.
- One tool, `read_file`, confined to `projects/harness/workspace/`. A path outside it is refused and stops the Run.
- A turn cap (default 10), and a Run log in JSON lines under `projects/harness/runs/`.

## Tickets and PRs

| Ticket | PR | Rework rounds | Outcome |
|---|---|---|---|
| <https://github.com/travism26/harness-lab/issues/7> | TODO: owner to fill in | TODO | TODO |
| <https://github.com/travism26/harness-lab/issues/8> | TODO: owner to fill in | TODO | TODO |
| <https://github.com/travism26/harness-lab/issues/9> | <https://github.com/travism26/harness-lab/pull/24> | TODO | merged |
| <https://github.com/travism26/harness-lab/issues/10> | this PR | TODO | TODO |

## What broke

TODO: owner to fill in from the factory runs and reviews of tickets 1-3. Nothing is recorded here that the repository does not show.

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

TODO: replace with permalinks (URLs with a commit SHA) once the PRs have merged.

## Live Run

Waiting on the owner's live Run with the `harness-lab-local` key. The owner adds its output as a comment on the Ticket; paste it here.

```
TODO: live Run output
```

### Tool calls in Anthropic's format

- **Haiku:** TODO: how it handled `tool_use` and `tool_result` blocks, from the live Run.
- **DeepSeek:** TODO: the same.
- **Did OpenRouter's Messages endpoint accept DeepSeek?** TODO: yes or no, with the evidence from the live Run.

## Cost

TODO: OpenRouter spend on the `harness-lab-local` key for the live Run, from the Run log's `usage` events.

## Open questions for the post

- TODO after the live Run.
