# Software factory concept

Condensed from the 2026-10-24 survey in claude-code-adw. The full timeline, practitioner table, reference diagram, stack notes, and gap list stay in [`concepts/software-factory-concept.md`](https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/concepts/software-factory-concept.md) at the pinned commit. Figures below are as those sources stated them. This page does not re-check them.

## Definition

A software factory, in the 2026 sense recorded in that survey, is a setup where coding agents write the code and also take part in deciding whether it merges. People supply intent (specs, scenarios, priorities) and design the machinery: the queue, the sandboxes, the verification, and the merge rules.

Two narrower uses show up in the same survey and are easy to mix:

- StrongDM's usage is non-interactive development: specs and scenarios drive agents that write code and converge without human review. Dan Shapiro's Level 5, the "dark factory", is the far end of that idea: specs go in and software comes out with no human process in between. Shapiro's level names and the claim about who sits at each level are his, cited in the source survey.
- Vendors also use "software factory" for any agent pipeline from ticket to pull request, including pipelines that still have human review. Factory.ai and Cursor Automations are cited there as this looser usage.

The survey's own one-line shift: the work moves from reviewing code to engineering how code gets verified. Simon Willison is cited calling the proof that agent-written code works the consequential problem. A factory is as trustworthy as its verifier.

## Spectrum

The source index draws three published points and says a project picks a point per kind of change. Auth, billing, migrations, and other one-way doors stay with a human in every source the survey treats as serious. HumanLayer is cited as having turned review back on after an outage in code nobody had read for three months.

| Point | Human role, as the sources describe it |
|---|---|
| Matt Pocock | A human approves the plan, reviews the pull request, and does QA. The away-from-keyboard loop cannot push. A codebase nobody reads is treated as a failure mode. |
| Lauren Tan (pstack) | A human sets the contract and the risk policy. Verifiers that did not write the code can authorize a reversible merge. The human audits main afterwards. |
| StrongDM | Humans write specs, scenarios, and the harness. The published rules say humans do not write the code and do not review it. |

## What the sources support

The survey separates claims it could tie to a primary or named secondary source from claims it could not. The gap list in the source file is part of the record: the OpenAI primary post returned 403, StrongDM's satisfaction scores are unpublished, and no controlled study of escaped defects was found.

Supported there, in the survey's wording:

- Long-running loops have produced large working systems when the feedback signal is strong. Cited examples include Cursor's browser research run and Anthropic's harness write-ups.
- An independent evaluator, a holdout set, or an end-to-end run of the real application is described as beating a self-grade. Anthropic's March 2026 harness post and StrongDM are the citations.
- Risk-tiered review is described as shipping: low-risk changes can be auto-approved, and high-risk ones go to humans. Cursor Automations and Factory.ai are the citations, both marked vendor in the source.

Treated there as hype or as not demonstrated:

- The flagship cases are small teams, and several headline results are self-reported.
- A green test suite is not the same as a pull request a maintainer would merge. METR's note of 2026-03-10 is the citation.
- When the same model writes, tests, and judges, the survey calls that circular verification.
- Organisation-wide telemetry cited from Faros points the other way on incidents and review time. The source marks it vendor and correlational.
- Ralph's author is quoted as not using that loop on existing codebases. Greenfield work, work with an external spec, and routine maintenance are the fits the survey lists. Novel product work and the hardest refactors are the poor fits.

Failure modes the same section lists, each with its citation in the source: agents rewriting tests to match the code, declaring victory early, lenient self-evaluation, context pressure near the window limit, duplicate implementations, a bad spec amplified at scale, humans losing track of the code, a maintenance cliff when nobody has read the code, CI load from agentic coding, and liability frameworks that assume a person looked.

Reported token spend in that section spans a $200 monthly plan, Anthropic's harness example of about $200 for a six-hour run, and StrongDM's target of at least $1,000 of tokens per engineer per day. Those figures are context for the research. They are not a budget for this repo.

## What this repo has settled

The design brief already picks a point on the spectrum, and it is the brief that governs:

- Draft pull requests only, a review step, two rework rounds, one ticket at a time, and a human merges.
- The factory starts only when the owner applies a label. Fork pull requests receive no secrets.
- Spend for this repo is about 20 USD on OpenRouter, split across two keys whose credit limits are the hard stop ([ADR 0004](../adr/0004-per-key-credit-limits-as-the-spend-stop.md)).
- The Harness calls Claude only through OpenRouter and never uses a subscription token ([ADR 0002](../../projects/harness/docs/adr/0002-openrouter-only-provider-and-sole-credential.md)). The Factory's Claude Code is the one place a subscription token is allowed, and only under the switch rule ([ADR 0003](../adr/0003-factory-claude-code-on-subscription-token-with-switch-rule.md)).

A run-the-app verifier, holdout scenarios, and verifier-authorized merge are research findings. They are not brakes in the design brief. Episode 5 is the planned post about shaping this repo so an agent can build and test it, using stand-in services. That episode is not written yet.

## Shaping the codebase

A later note in the same corpus, [`concepts/agent-friendly-codebase.md`](https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/concepts/agent-friendly-codebase.md) (2026-10-28), records a field survey of how to make a repo one an agent can work in. Its short answer: the nearest pattern should be the right one, the shortest wrong path should fail a check that names the right path, and independent work should land in independent files. The note's audit checklist, boundary-tool configs, and per-stack sections stay at the source. This repo has not adopted that audit.

The companion Dune-contract dissection is an ADW-oriented reading of the same ideas and stays at the source. See [provenance.md](provenance.md).

## Which harness runs the factory

[`concepts/claude-code-as-harness.md`](https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/docs/research/software-factory/concepts/claude-code-as-harness.md) is a capability survey of Claude Code as of 2026-10-24 (local build 2.1.310 in that note). Its conclusion, which this record keeps and its table does not:

- Supervised work of the kind the research describes can sit inside Claude Code: a coordinator, nested subagents, a restricted verifier, worktrees, and saved workflows.
- An unattended run is the gap that note names. Its listed options are a cloud scheduled task, a GitHub Action, or a thin local loop around the headless CLI.
- A verdict that the agent cannot influence still needs a deterministic component. The note says that component can be a hook, an Action, or the thin driver. It does not have to be a separate harness project.

This repo's settled factory is the GitHub Actions option, with Claude Code as the agent inside it. The teaching Harness is a raw API loop written so readers can see the loop ([ADR 0001](../../projects/harness/docs/adr/0001-raw-api-loop-without-agent-sdk.md)). Cursor, Claude Code, and that small program are three different places a factory's agent can run. The research does not require them to be the same system.
