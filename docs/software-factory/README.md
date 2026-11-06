# Software-factory research

This folder is a research record consolidated from [claude-code-adw](https://github.com/travism26/claude-code-adw). It is a reading of other people's workflows and of decisions recorded there on 2026-10-24. It is not the specification of this repo's Factory, and it does not describe a harness loop or factory workflow that exists on `main`.

**Settled for this repo.** The [design brief](../design.md), the [glossary](../../GLOSSARY.md), and the [decision records](../adr/) say what the Factory is here: the GitHub Actions setup that turns labelled issues into draft pull requests, with a review step and a human merge. The Harness is a separate object, the small program the series teaches.

**On `main` today.** Those design documents are what is implemented. Factory workflows and harness-loop code are not on `main` (destination base `41265c5d8c243457cb89f2e9d84997a5f42e3ebc`). The open skeleton pull request [harness-lab#3](https://github.com/travism26/harness-lab/pull/3) adapts factory workflows from [claude-code-adw#8](https://github.com/travism26/claude-code-adw/pull/8). This record does not absorb that pull request and does not copy its operating docs.

**Source, left untouched.** [travism26/claude-code-adw](https://github.com/travism26/claude-code-adw) at [`b2e37ed6be82085269ce2c12a4035111b2a9994a`](https://github.com/travism26/claude-code-adw/commit/b2e37ed6be82085269ce2c12a4035111b2a9994a) (committed 2026-11-05). Both repositories were public when this consolidation was written. Every considered file, and whether its substance was rewritten here or left at the source, is in [provenance.md](provenance.md).

## What this record means by a software factory

A software factory is a way of working in which agents write the code and the decision to merge is engineered. People keep the intent, the risk policy, and the choice of machinery. That machinery can be Claude Code, Cursor, GitHub Actions, or a purpose-built program. A factory does not have to be a custom harness.

This repo uses the words for two specific things. The Factory is the GitHub Actions setup. The Harness is the teaching program. The research notes use "software factory" for the broader idea. See [Vocabulary](#vocabulary).

## Reading order

| File | What it holds |
|---|---|
| [concept.md](concept.md) | Definition, the spectrum of human involvement, what the sources support, and the choices this repo has already recorded |
| [workflows.md](workflows.md) | Matt Pocock's and Lauren Tan's workflows as studied, and where the surveyed workflows agree and differ |
| [aspirations.md](aspirations.md) | The 2026-10-24 research grill (R1–R15), kept as proposals, and where those proposals differ from this repo |
| [provenance.md](provenance.md) | The source commit and the retain or consolidate rationale for each file |

The sourced surveys, the dissections, the Spring/Rust/Node notes, and the ADW pipeline stay in claude-code-adw. The provenance table links each one at the pinned commit.

## Vocabulary

The root [glossary](../../GLOSSARY.md) is the language of this repo. The research glossary in the source defines a second set, including Check, Verification, Verdict, Claim, Review, Author, Verifier, Task, Trigger, Run, and Runner. Those terms are not added to the root glossary.

| Research word | This repo | How to read both |
|---|---|---|
| Factory, in the broad sense | Factory: the GitHub Actions setup that builds the Harness | Use the root glossary for this repo. Use "software factory" for the research idea. |
| Review: reading a diff without running the application | The factory review step on a pull request | The same word covers two procedures. The design brief names the one this repo uses. |
| Ticket | Ticket: a GitHub issue written for the factory | The same object. The research word Task is a kind of work, not a Ticket. |
| Ticket tracker, with an instruction to avoid "issue tracker" | GitHub Issues, in [docs/agents/issue-tracker.md](../agents/issue-tracker.md) | This repo keeps the name "issue tracker". |
