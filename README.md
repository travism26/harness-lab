# harness-lab

A public, for-fun lab for experimenting with **AI-assisted software engineering**: agent harnesses, autonomous software factories, coding agents like Claude Code, agent identity and observability.

The twist is that the lab mostly runs itself. AI agents find ideas, plan them and build them, and a human approves the spec and merges the PR.

## What we're experimenting with

- **A software factory on GitHub Actions.** A labelled GitHub issue (a Ticket) becomes a **draft PR** built by Claude Code. An independent read-only agent reviews it for Spec and Standards. Up to two automatic rework rounds follow, and a human merges. See [the factory](docs/factory/README.md).
- **Agents that find and plan their own work.** Two scheduled Grok bots feed the factory. Their setup prompts are in [docs/factory/grok-bots.md](docs/factory/grok-bots.md):
  - a **Scout** that reads what practitioners are shipping in AI engineering and files concrete `Goal:` issues;
  - a **Builder** that grills each Goal with [Matt Pocock's skills](https://github.com/mattpocock/skills) (`grill-with-docs`, `to-spec`, `to-tickets`), answers its own questions from the repo's docs, and publishes a spec and tickets.

  The chain they run is in [the skill chain](docs/factory/skill-chain.md). [Goal #108](https://github.com/travism26/harness-lab/issues/108) is a real example: the Goal, its four grill rounds, the test-seam answer and the ticket breakdown are all comments on that issue.
- **Labels as the state machine.** The bots never talk to each other. Each one reads a GitHub label, does its part, sets the next label and stops. That makes every step visible, resumable and auditable.
- **Brakes for autonomous coding agents.** The factory uses:
  - draft PRs only, and the factory can't merge;
  - one Ticket at a time;
  - daily run caps and a dollar cap on every agent run;
  - no GitHub token in the agent's hands;
  - no secrets for fork PRs;
  - factory scripts loaded from `main`, so a PR can't edit the brakes that judge it.

  See [ADR 0005](docs/adr/0005-label-only-factory-start-and-no-secrets-for-forks.md) and [ADR 0007](docs/adr/0007-factory-scripts-from-the-default-branch-agents-without-github-token.md).
- **Proof over claims.** Every project has an executable `check` script, and an agent saying "done" counts for nothing until that check passes.

```
Scout ──Goal issue──► Builder ──spec──► human approves ──tickets──► Factory ──draft PR──► human merges
```

## Projects

| Project | What it explores |
|---|---|
| [harness](projects/harness/) | A small agent harness built in public, one blog post per episode. |
| [agent-identity](projects/agent-identity/) | Giving an AI agent its own SPIFFE identity. The Model only proposes, a Warden decides from fixed rules, and a Broker holds the model key so the Agent never does. Runs offline with `cd projects/agent-identity && go run ./cmd/demo tour`. None of it is production security. |
| [ai-gateway](projects/ai-gateway/) | A loopback gateway between Claude Code and the Anthropic API. It appends one Call record per Call and holds no credential. |

Most of this code was written by the factory from Tickets. Browse the [closed issues](https://github.com/travism26/harness-lab/issues?q=is%3Aissue+is%3Aclosed) and [merged PRs](https://github.com/travism26/harness-lab/pulls?q=is%3Apr+is%3Amerged) to follow the full idea → spec → ticket → PR history, including the agents' grill rounds and review reports.

## Reading map

- The owner's [setup guide](docs/factory/setup.md): how the factory's credentials are wired.
- [Glossary map](GLOSSARY-MAP.md), the lab [glossary](GLOSSARY.md) and [decision records](docs/adr/): the terms used here and the hard-to-reverse choices.
- [Software-factory research](docs/software-factory/README.md): notes consolidated from [claude-code-adw](https://github.com/travism26/claude-code-adw) at `b2e37ed`.

## Running the tests

```bash
uv run pytest
```

From the repo root, this runs the Python projects' tests, the factory's and Harness's. Each Go project has its own check:

```bash
cd projects/agent-identity && ./check
cd projects/ai-gateway && ./check
```

Each runs gofmt, vet, staticcheck, trustlint and the race-enabled tests.

## Contributing

This is a personal learning lab, and work enters through the owner's labels. Opening an issue or PR doesn't start the factory, and fork PRs get CI only. Questions and ideas are welcome, but expect a slow, hobby-paced reply.

Licensed under the [MIT License](LICENSE).
