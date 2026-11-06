# Workflows that were studied

The 2026-10-24 workflow map in claude-code-adw compares six workflows on one grid: Lauren Tan's pstack (plus Cursor-native pieces), Matt Pocock's skills plus Sandcastle, StrongDM, Geoffrey Huntley's Ralph loop, Anthropic's long-running-harness posts, and the ADW pipeline in that repo. The grid, the conflict write-ups, the dissection backlog, and the ADW borrow sheet stay in [`workflow-map.md`](https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/workflow-map.md). The StrongDM, Ralph, and Anthropic columns are thinner: the map says they were filled from the concept survey, not from a fresh reading of those primary pages.

This page keeps the two workflows that were read from installed skills and public material, the agreements the map records, and the differences that change how to read this repo. It does not adopt the borrow sheet.

## Pocock

Source write-up: [`workflows/matt-pocock/overview.md`](https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/workflows/matt-pocock/overview.md), dated 2026-10-24. Method stated there: the skills then installed under the author's `~/.agents/skills/`, checked against `~/.agents/.skill-lock.json` and `mattpocock/skills`, plus the public Sandcastle repo and talks. That local install was not re-checked for this consolidation. See the skill inventory in the pull request that added this folder.

As that note summarizes it, the day shift is human: grill, approve the spec's test seams, approve the ticket breakdown, and only then label work `ready-for-agent`. The night shift is an away-from-keyboard loop (Ralph, packaged as Sandcastle) in a sandbox. It takes one unblocked ticket, builds it, runs checks, and commits. A fresh-context reviewer may edit the branch. The human returns for QA, a diff review, and the merge. Agents are instructed not to push. His glossary, as quoted in the note, treats a dark factory as a failure mode.

The same note says his skills have no dedicated "run the app and observe" verifier. Feedback loops (types, tests, browser access, hooks) are the stated speed limit, and human QA is what caught a case where tests were green and a database table was missing.

A 2026-11-02 follow-up in [`matt-pocock-course/`](https://github.com/travism26/claude-code-adw/tree/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/matt-pocock-course) reads his public skills PRs, his GitHub Actions examples, and the public course page. It stays at the source, including the ADW adoption game plan. The finding that overlaps this repo's design brief, and is already settled there rather than imported from the follow-up: brakes before extra triggers, draft pull requests, and a human at merge. His `software-factory` skill is a glossary for designing a factory on infrastructure the reader chooses. The dissection of that skill stays at the source. Its terms are not this repo's glossary. See [README.md](README.md#vocabulary).

## Poteto

Lauren Tan's public account and the pstack reconstruction stay in:

- [`workflows/poteto/public-workflow.md`](https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/workflows/poteto/public-workflow.md)
- [`workflows/poteto/how-she-develops.md`](https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/workflows/poteto/how-she-develops.md)
- [`workflows/poteto/pstack-mechanics.md`](https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/workflows/poteto/pstack-mechanics.md)
- [`workflows/poteto/repos-and-evolution.md`](https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/workflows/poteto/repos-and-evolution.md)
- [`workflows/poteto/cursor-native-pieces.md`](https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/workflows/poteto/cursor-native-pieces.md)

The index states the shape in one page. Trust comes before parallelism: stay with a few supervised agents until their checks are trusted. A per-app verification skill drives the real application and is treated as critical infrastructure. The codebase is the memory: one blessed way to do each thing, and a repeated correction becomes a check. An overnight run is a contract with a done condition that can fail, an isolated workspace, verifiers that did not write the code, and a decision log. A duration is not a finish condition. Irreversible actions wait. Merging is the guarded step: a verdict has to match the code that lands (`git patch-id` is the mechanism the notes name). In the morning the human reads main and reverts or adds a check. The index also records the caveats attached to that account: numbers are self-reported, the setting is an AI lab with a large token budget, and the first unattended night is described as frightening.

pstack is agent workflow tooling. It can run inside Cursor, and the source notes also describe a Claude Code install. It is not an application runtime, and it is not this repo's Factory. The Cursor-native pieces (automations, the orchestrate plugin, and the other plugins in that note) are a separate layer from the Claude Code build. Their Claude Code stand-ins, where the note proposes any, stay in that file.

The dissections under `dissections/poteto/` turn those mechanisms into designs aimed at ADW (`verdict_check.py`, an `adw night` sketch, a queue driver). They stay at the source.

## Where they agree

Recorded in workflow-map section 5, as observations about the surveyed workflows. They are not a design added for this repo. The design brief remains the design.

1. The writer does not grade its own work. Fresh-context review, a non-author verifier, a separate evaluator, or a holdout set are the forms the map lists. Ralph is the exception the map names, and the map says later versions added review.
2. Verification, not generation, is the bottleneck.
3. Something runs the real system, or a human does that QA when the tools do not.
4. State that must survive a session lives on disk and in git.
5. One unit of work gets a fresh context.
6. Deterministic work goes in ordinary code. Judgment goes to the model.
7. A repeated lesson becomes a check or a structural constraint.
8. Runs have a stop that is not "keep going until the clock ends".
9. Irreversible actions stay with a human.
10. Trust is earned on one agent before the count goes up.
11. Humans keep the spec and the risk policy.

## Where they differ

The map's section 4 is the full list. These four are the ones that change a reading of this repo:

| Question | Pocock, as studied | Poteto / pstack, as studied | Settled in this repo |
|---|---|---|---|
| Who merges | A human, after QA | A non-author verdict on that patch can merge under a full-autonomy grant. Otherwise a human does | A human merges |
| When intent is fixed | Grill until the open questions are settled, before the away-from-keyboard run | An experiment can settle an empirical question during the run. Irreversible actions wait | Grill, then tickets, before the factory runs |
| Pull request state | The loop stops at a reviewable branch or pull request | The mechanics note describes pull requests opened ready | Draft only |
| What counts as done | Types, tests, then human QA | A per-app skill drives the real app. The author does not grade | The review step reads the diff. A run-the-app verifier is not a brake in the design brief |

## ADW stays at the source

[`workflows/adw/overview.md`](https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/workflows/adw/overview.md) is a stage-by-stage reading of claude-code-adw's own pipeline: Python under `adws/` driving Claude Code from a ticket to a draft pull request a human merges. Its operating docs (`docs/factory/`), its skills (`.claude/skills/`), and its milestone plans stay in that repo. They are implementation and operating notes for that harness, not general factory material.

harness-lab's Factory is the GitHub Actions setup in the design brief, committed on `main` by merged [harness-lab#3](https://github.com/travism26/harness-lab/pull/3). The operating description is [the factory doc](../factory/README.md). This folder does not restate it.
