# ticket-sizer

Its one job: read one Lab issue from a local fixture and propose which workflow scenario it is.

It is the second agent in `projects/agents/` and still a proof of concept of the pattern. The layout and the rules it follows are in `projects/agents/README.md`. The scenarios, and the flow each one gets, are defined in section 3 of `docs/skill-workflows.md`, which lists this agent as an idea in section 5.

## What it does

The agent has one tool, `read_issue`, served in-process as `mcp__issues__read_issue`. It takes one input, a bare fixture name, and returns the text of `projects/agents/ticket-sizer/evals/fixtures/<name>.md`. The model then returns a proposal: a `scenario` and a short `reason`.

The scenario is one of `small`, `medium`, `big`, `huge`, `poc`, `bug` or `unattended`. The runner, not the model, decides whether the proposal stands. It is a failed run, logged as `invalid_output`, when the label is not on the list, the reason is missing or blank, or the output does not parse. It is `tool_not_run` when the model proposed a label without the tool ever returning the fixture it was asked about.

## How the fixture tool is confined

The tool can read only `projects/agents/ticket-sizer/evals/fixtures/`. The code is `readFixture` in `projects/agents/ticket-sizer/src/fixtures.ts`:

- The name must match `[A-Za-z0-9][A-Za-z0-9_-]*`. That rules out `/`, `\`, `..`, a leading dot, an absolute path and an extension before any file is touched. The code adds `.md` itself.
- The file must be a regular file, not a symlink, and its resolved path must still be inside the fixtures directory.
- A fixture over 20000 characters is refused.

`projects/agents/ticket-sizer/test/fixtures.test.ts` tests each of these without a model. The agent has no `Read`, `Bash`, web tool, GitHub API or `gh`. The GitHub issue text in the fixtures was copied in by hand when the fixtures were written; nothing fetches it at run time.

## What it must not do

It does not call the GitHub API, change a label, size a Ticket as ready for the factory, or work with other agents. `workflow-auditor` is a separate idea and is not here.

## How it is boxed in

The settings are in `projects/agents/ticket-sizer/agent.json`, and `buildOptions` in `projects/agents/ticket-sizer/src/config.ts` is the one place that turns them into SDK options. They are the same as the identity tester's, with `low` effort.

- `model` is `claude-haiku-5-5`, at `low` effort.
- `maxTurns` is 12 and `maxBudgetUsd` is 0.10. Both are the starting values in `projects/agents/README.md` and the limits Goal #191 set, well under that README's maxima of 30 turns and $1. `projects/agents/ticket-sizer/test/config.test.ts` fails if either is raised. A run should need about three turns; no live run has measured that yet.
- `settingSources` is `[]`, `strictMcpConfig` is on and `persistSession` is off.
- `tools` is `[]`, which removes every built-in tool. `disallowedTools` names `Bash`, `Write`, `Edit`, `NotebookEdit` and the other built-ins anyway. `allowedTools` holds only `mcp__issues__read_issue`, and `permissionMode` is `dontAsk`.
- A `PreToolUse` hook denies any tool that is not that one, apart from `StructuredOutput`, which the SDK adds to carry the proposal.

The SDK is `@anthropic-ai/claude-agent-sdk` 0.3.330, pinned in `projects/agents/ticket-sizer/package.json` and its lockfile. The SDK's `tool()` takes its input as a zod shape, and zod is a peer dependency the SDK already requires, so `zod` is pinned beside it at the version the lockfile already held. `projects/agents/ticket-sizer/src/main.ts` is the only file that imports it, so the tests and `projects/agents/check` need no install.

## Outcomes

Every run ends in exactly one outcome. It is in the output, in the run log and in the exit code.

| Outcome | Meaning | Exit code |
| --- | --- | --- |
| `sized` | A valid label and a reason, and the fixture was read. | 0 |
| `invalid_output` | A label off the list, a missing or blank reason, or output that does not parse. | 2 |
| `tool_not_run` | A valid proposal, but the fixture was never read. | 2 |
| `denied_tool` | The model tried a tool it does not have. | 2 |
| `max_turns`, `max_budget` | A cap ended the run. | 2 |
| `error` | Anything else, such as an API error. | 2 |

## Check it without a model

```
projects/agents/check
```

This runs the unit tests and grades the eval set with Node alone. To check the runner's types against the pinned SDK, from this folder:

```
npm ci
npm run typecheck
```

## The eval set

`projects/agents/ticket-sizer/evals/cases.jsonl` has eleven cases. Each names a fixture, where its text came from (`source`), a recorded proposal and the outcome a correct grader gives it. `node evals/grade.ts` grades them with the same `gradeProposal` the runner uses. No model is called, so the grader tests the code that checks a proposal. It cannot say whether Haiku picks the right label. The proposals are hand-written stand-ins for model output.

| Case | Fixture | Expects | Source |
| --- | --- | --- | --- |
| `small-typo` | `typo-readme` | `small` | hand-written |
| `medium-go-sandbox` | `go-sandbox-goal` | `medium` | issue 174, trimmed |
| `big-run-records-spec` | `run-records-spec` | `big` | issue 141, trimmed |
| `huge-clickhouse-map` | `clickhouse-map` | `huge` | issue 159, trimmed |
| `poc-stop-hook` | `stop-hook-experiment` | `poc` | issue 193, trimmed |
| `bug-metrics-crash` | `metrics-crash-bug` | `bug` | hand-written |
| `unattended-overnight` | `overnight-run` | `unattended` | hand-written |
| `label-not-on-list`, `factory-label-is-not-a-scenario`, `empty-reason`, `wrong-case-label` | various | `invalid_output` | hand-written model output that must be rejected |

The issue numbers are public `travism26/harness-lab` issues. The grader also fails when a fixture is unused, no case expects `small` or `huge`, or every case expects `medium`.

## Run it live

A live run calls the Anthropic API and costs money (a fraction of a cent, capped at $0.10). It is never part of the check or of CI. From this folder, with the key in your environment and the name of one fixture:

```
npm ci
ANTHROPIC_API_KEY=... npm start -- typo-readme
```

The key is read from the environment at run time and is not written anywhere. The output is printed as JSON, and one line is appended to `runs/log.jsonl`, which git ignores. `runs/sample.jsonl` shows the shape, with made-up numbers. Compare the printed `proposal.scenario` with the `expect` of that fixture's case by eye; the live run is not graded automatically.
