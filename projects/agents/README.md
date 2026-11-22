# agents

A for-fun layout for small agents that each do one narrow job. Every agent is one folder with its own prompt, a tool list of two or three tools, a pinned cheap model, hard caps, an eval set and a run log. The first one is `projects/agents/identity-tester/`, which tests `projects/agent-identity`. The next ones start as a copy of `projects/agents/_template/`.

The idea comes from Justin Schroeder's talk [Why Domain-specific Agents Are the Future](https://www.youtube.com/watch?v=wIPr9GmLRaQ) and the [Standard Agent Spec overview](https://standardagentspec-com.pages.dev/0.1.0/getting-started/overview): an agent is deterministic software around a model call, and a specialist with its own tools beats one general agent holding every tool. This Project uses the TypeScript [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/typescript), not that spec's runtime. Running several of these agents together is later work and not part of this Project.

## One folder per agent

Each agent folder has at least these files. `projects/agents/check` fails when one is missing.

| File | What it holds |
| --- | --- |
| `README.md` | The single job, in one sentence, and what is outside it. |
| `agent.json` | The pinned model id, the turn and budget caps, the tool allowlist and denylist, and the run-log location. |
| `prompt.md` | The system prompt. |
| `evals/cases.jsonl` | The agent's own eval set: recorded cases, each with the outcome a correct run reaches. |
| `runs/.gitignore` and `runs/sample.jsonl` | Where run logs go, and the shape of one line. |

An agent that runs also has `package.json` and `package-lock.json` (the SDK pinned to one exact version), `src/main.ts` (the runner) and `evals/grade.ts` (the grader for its cases).

## What `agent.json` must say

The runner passes these values to the SDK's `query()` unchanged, and the check holds every agent folder to them.

| Field | Rule | Why |
| --- | --- | --- |
| `name` | The folder's name. | The run log and the report carry it. |
| `job` | One sentence. | If it takes an "and" to say it, that is two agents. |
| `model` | `claude-haiku-5-5`. | A concrete id set in the repo, not whatever the SDK defaults to. |
| `effort` | `low` or `medium`. | Higher effort more than doubles output tokens. |
| `maxTurns` | 1 to 30. Start at 12. | A run that loops stops. |
| `maxBudgetUsd` | Above 0, at most 1. Start at 0.10. | The SDK estimates cost on the client and can overshoot a little, so this is a brake and not an invoice. |
| `settingSources` | `[]`. | Your own Claude Code settings, `CLAUDE.md` files and project settings stay out of the agent. |
| `permissionMode` | `dontAsk`. | A call that would prompt is denied instead. |
| `tools` | The built-in tools the agent keeps. Never `Bash`, `Write`, `Edit` or `NotebookEdit`. `[]` removes them all. | The model cannot call a tool it was never given. |
| `allowedTools` | The tools the job needs, by full name (`mcp__<server>__<tool>` for a custom tool). No globs. | Only these are approved. |
| `disallowedTools` | At least `Bash`, `Write`, `Edit` and `NotebookEdit`. | A deny rule wins over everything else. |
| `runLog` | A `.jsonl` path under `runs/`. | One place per agent. |

`allowedTools` on its own is not a sandbox. In `dontAsk` mode the SDK still runs calls that never need approval, such as a file read in the working directory or a read-only shell command ([permissions](https://code.claude.com/docs/en/agent-sdk/permissions)). That is why `tools` and `disallowedTools` are set as well, and why the runner adds a `PreToolUse` hook that denies every tool outside the list.

## The model proposes, code decides

The tools record what happened (an exit code, a status) in code. The model's structured output is a proposal. The runner compares it with what the tools recorded and throws the run away when they disagree. So the pass or fail in the final output never rests on the model's word.

A run that hits a turn or budget cap, has a tool call denied, or returns output that fails the schema is a failed run. It is logged as one and exits non-zero.

## The run log

Each live run appends one JSON line to the agent's `runs/log.jsonl`, which git ignores. `runs/sample.jsonl` is committed and shows the shape:

| Field | Meaning |
| --- | --- |
| `ts` | When the run ended, as an ISO timestamp. |
| `agent` | The agent's name. |
| `model` | The pinned model id. |
| `turns` | Turns the SDK reported. |
| `cost_usd` | The SDK's client-side cost estimate. |
| `outcome` | How the run ended. `max_turns`, `max_budget`, `denied_tool`, `invalid_output` and `error` mean the same thing for every agent. An agent adds its own values for runs that finish. |
| `detail` | A short reason, or an empty string. |
| `duration_ms` | Wall-clock time of the run. |

An agent may add fields. The API key never goes in a log line or a report. The runner reads it from the environment and redacts it from every string it writes.

## Evals

Each agent keeps its own eval set in `evals/cases.jsonl`: one JSON object per line, with a unique `id`, what was recorded, and `expect`, the outcome a correct run reaches. Cases come from real output, and some of them are failures. `evals/grade.ts` grades them with plain code and exits non-zero when a case comes out wrong. The grader checks the outcome, not which tool calls led to it.

## The check

```
projects/agents/check
```

It checks the layout of the template and of every agent folder, holds each `agent.json` to the table above, runs each agent's `evals/grade.ts`, runs the unit tests, and looks for anything shaped like an API key. It uses only Node built-ins (Node 22.18 or newer, which runs TypeScript directly). It installs nothing and makes no network or model call. CI runs it on every pull request that touches this folder. No CI job calls a model.

Checking the runner's types against the SDK needs the SDK installed, so that is a separate local step in each agent folder: `npm ci && npm run typecheck`.

## Start a new agent

1. Copy the template: `cp -r projects/agents/_template projects/agents/<name>`.
2. Run `projects/agents/check`. It lists what is left, including every `REPLACE-ME`.
3. Fill in `README.md`, `agent.json` and `prompt.md`. Keep the tool list to what the job needs.
4. Copy `package.json`, `package-lock.json`, `tsconfig.json`, `.npmrc` and `src/` from `projects/agents/identity-tester/`, give the package its own name, and rewrite the parts that belong to the job: the commands or calls behind the tools, the report schema, and the grader.
5. Record real cases, with failures among them, into `evals/` and make `evals/grade.ts` grade them.
6. Run `projects/agents/check` until it passes. Only then do a live run.

## What it costs

Haiku 5.5 list prices, retrieved 2026-11-21 from the [pricing page](https://platform.claude.com/docs/en/about-claude/pricing), for prompts up to 100k tokens: $0.10 per million input tokens, $0.50 per million output tokens, $0.01 per million cache-read tokens. A sketch of one tester run: about 8k new input tokens, 4k cache-read and 4k output comes to about $0.003. The one measured run so far (2026-11-22, a passing tree) took 4 turns and the SDK estimated it at $0.0011. At 20 runs a day either figure is under $2 a month. The caps above keep one bad run from costing more than `maxBudgetUsd`, give or take the estimate's overshoot.
