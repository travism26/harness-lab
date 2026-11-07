# Research proposals from 2026-10-24

[`decisions-to-grill.md`](https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/decisions-to-grill.md) records a grilling session in claude-code-adw. The settled rows below are proposals for a personal pilot that would learn two existing workflows and, later, a personal Claude Code plugin. They are not decision records of harness-lab. They do not change [docs/design.md](../design.md) or anything under [docs/adr/](../adr/).

The open question list in that file (autonomy per risk tier, who owns the oracle, loop shape, liveness, cost ceilings, and the extra questions from each dissection) was an agenda. It stays at the source. Nothing in this folder answers it.

The curriculum that turns R1–R15 into four supervised exercises on private pilot repos also stays at the source: [`curriculum.md`](https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/curriculum.md). It tells the reader to keep pilot repo names out of the public file. This consolidation does not add them.

## Recorded proposals

| Id | Recorded on 2026-10-24 | Status here |
|---|---|---|
| R1 | Next phase is supervised use of existing workflows on real work, before designing a new one | Proposal for that pilot |
| R2 | Pilot on a personal repo, not the work Spring Boot service | Proposal for that pilot |
| R3 | Tan-style verifier merge for low-risk tiers; Pocock-style human merge otherwise. Never a dark factory | Proposal. See the table below |
| R4 | Budget: Claude Max 5x, moderate use. No swarms. Model-tiering later | Proposal for that pilot |
| R5 | Claude Code only for now. A second model family is a later experiment | Proposal for that pilot |
| R6 | Use the research terms Check, Verification, Verdict, Claim, Review, Author, Verifier. Retire "validation" | Research vocabulary. The root glossary is unchanged |
| R7 | Next phase is a curriculum: one lesson per stage, verify first | The curriculum stays at the source |
| R8 | The eventual workflow is a personal Claude Code plugin in its own repo, with per-repo recipes. claude-code-adw is reference only | Proposal for a plugin that was not created by this change |
| R9 | During the pilot, mix pstack and Pocock's skills and log conflicts | Proposal for that pilot |
| R10 | Interactive Claude Code for the pilot. An unattended layer later. No external orchestrator | Proposal. See the table below |
| R11 | Two personal pilot repos, named only in an uncommitted `pilot-log/` | Proposal for that pilot |
| R12 | Leave the pstack model config where it already was: `~/.claude/rules/pstack-models.md` | A path named in the research note. It is not a file in this repo, and this consolidation did not read that home directory |
| R13 | Exercise order: verification skill, then a bug fix via poteto-mode, then a feature via Pocock's grill/spec/tickets/implement, then a feature via poteto-mode | The exercise script stays at the source |
| R14 | Pilot notes go in `pilot-log/`, never committed | Unchanged. Nothing from a pilot log is in this repo |
| R15 | Retro after the four exercises, not on a date | Proposal for that pilot |

## Where the proposals differ

| Proposal | What this repo has already recorded |
|---|---|
| R3, verifier merge on low-risk tiers | The design brief: a human merges every factory pull request. "Never a dark factory" is the part that matches. Low-risk self-merge is not a brake or a goal in the brief. |
| R4, Claude Max 5x as the budget | [ADR 0004](../adr/0004-per-key-credit-limits-as-the-spend-stop.md): about 20 USD on OpenRouter, two keys, the key limit is the stop. |
| R5, Claude Code only | The Factory's agent is Claude Code, with the switch rule in [ADR 0003](../adr/0003-factory-claude-code-on-subscription-token-with-switch-rule.md). The Harness calls Claude through OpenRouter and does not use a subscription token ([ADR 0002](../adr/0002-openrouter-only-provider-and-sole-credential.md)). |
| R8, a personal plugin, and claude-code-adw as reference only | This repo is the series repo the Factory builds. The Harness is a small program in this repo, not a Claude Code plugin. |
| R10, no external orchestrator | The Factory is GitHub Actions. That is the orchestrator the design brief specifies. |
| R12, a user-level pstack model file | This repo commits no model map. A user-level file, if it exists on a given machine, is outside this repository. |

## Shared shape already settled here

These items show up in both the research notes and the design brief. The brief is the one that applies. The notes are where the same shape was studied under other names.

- A human settles intent before an agent implements a ticket.
- Brakes come before extra triggers: draft pull requests, a review step, a rework cap, one ticket at a time, a human merge.
- The owner applies the label that starts work. Opening an issue does not ([ADR 0005](../adr/0005-label-only-factory-start-and-no-secrets-for-forks.md)).
- The series plan after the design documents is the one in the design brief: the skeleton factory, then episode tickets. It is not the four-exercise pilot.
