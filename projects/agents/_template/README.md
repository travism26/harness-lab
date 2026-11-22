# REPLACE-ME: the agent's name

REPLACE-ME: one sentence that says the single job this agent does. If it takes an "and" to say it, that is two agents.

This folder is the skeleton every agent under `projects/agents/` starts from. The conventions, and the steps for turning a copy into a working agent, are in `projects/agents/README.md`.

| File | What it holds |
| --- | --- |
| `agent.json` | The pinned model id, the turn and budget caps, the tool allowlist and denylist, and where the run log goes. |
| `prompt.md` | The system prompt. |
| `evals/cases.jsonl` | The eval set: one recorded case per line, with the outcome a correct run reaches. |
| `runs/sample.jsonl` | The shape of one run-log line. Live runs append to `runs/log.jsonl`, which git ignores. |

## What it must not do

REPLACE-ME: list what is outside the job, so the tool list stays small.
