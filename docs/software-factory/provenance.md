# Provenance and coverage

Audit list for this consolidation. Source files were read at the commit below and were not modified. No file was copied byte for byte. "Consolidate" means the useful general substance was rewritten into the destination section named here, and the source file remains the detailed record. "Retain" means the file stays only at the source, with the link below as the pointer.

## Source pin

| Field | Value |
|---|---|
| Repository | [travism26/claude-code-adw](https://github.com/travism26/claude-code-adw) |
| Commit | [`b2e37ed6be82085269ce2c12a4035111b2a9994a`](https://github.com/travism26/claude-code-adw/commit/b2e37ed6be82085269ce2c12a4035111b2a9994a) |
| Commit date | 2026-11-05 |
| Default branch at pinning | `main` |
| Visibility at pinning | Public, confirmed with `gh repo view` and `gh api` (`visibility: public`, `private: false`) for both this repo and the source |
| Destination base | `41265c5d8c243457cb89f2e9d84997a5f42e3ebc` on `main` |
| Tree | `docs/research/software-factory/` (32 files) |

Blob URLs in the tables are `https://github.com/travism26/claude-code-adw/blob/b2e37ed6be82085269ce2c12a4035111b2a9994a/<path>`.

## How to read the dispositions

| Disposition | Meaning |
|---|---|
| consolidate | General software-factory substance rewritten into a short doc in this folder. Duplication across the source corpus was folded into one place. Aspirations stay labelled as proposals. |
| retain | ADW harness implementation, ADW operating docs, ADW-targeted designs, dated catalogues, or material whose detail would become a second architecture if copied. |

## Software-factory files

| Path | Lines | Disposition | Lands in | Rationale |
|---|---|---|---|---|
| `docs/research/software-factory/README.md` | 100 | consolidate | [README.md](README.md) | The one-page picture and the scope warning ("research only") are the folder introduction. The ADW skill-gap list in that file is about `verify` / `ship-gate` and stays at the source. |
| `docs/research/software-factory/GLOSSARY.md` | 101 | retain | source only | Research terms. They collide with this repo's Factory, Review, and issue-tracker language, so they were not merged into the root glossary. The collision is in [README.md](README.md#vocabulary). |
| `docs/research/software-factory/guide.html` | 792 | retain | source only | Single-page HTML rendering of the whole corpus, including the ADW column. This repo's docs are markdown. |
| `docs/research/software-factory/curriculum.md` | 465 | retain | source only | Supervised exercise script for private pilot repos, with `/pstack:` commands. The intent is summarized as R7 and R13 in [aspirations.md](aspirations.md). |
| `docs/research/software-factory/decisions-to-grill.md` | 65 | consolidate | [aspirations.md](aspirations.md) | R1–R15 are recorded as proposals, with the rows that differ from this repo called out. The open question agenda stays at the source. |
| `docs/research/software-factory/workflow-map.md` | 283 | consolidate | [workflows.md](workflows.md) | The agreements, and the differences that change a reading of this repo, are kept. The six-column grid, the dissection backlog, and the ADW borrow sheet stay at the source. |
| `docs/research/software-factory/concepts/software-factory-concept.md` | 293 | consolidate | [concept.md](concept.md) | Definition, spectrum, supported claims, hype, and failure modes. The timeline, practitioner table, reference diagram, Spring/Rust/Node notes, and gap list stay at the source. |
| `docs/research/software-factory/concepts/claude-code-as-harness.md` | 44 | consolidate | [concept.md](concept.md#which-harness-runs-the-factory) | The conclusion that the factory harness can be Claude Code, a GitHub Action, or a thin loop. The 2026-10-24 capability table stays at the source. |
| `docs/research/software-factory/concepts/agent-friendly-codebase.md` | 389 | consolidate | [concept.md](concept.md#shaping-the-codebase) | The field's short answer. The audit checklist and boundary-tool configs stay at the source so they are not adopted as a new process here. |
| `docs/research/software-factory/verification/skills-comparison.md` | 263 | retain | source only | Compares this source repo's `verify`, `validate-work`, and `ship-gate` skills with pstack and Pocock, and lists changes to those skills. |
| `docs/research/software-factory/workflows/adw/overview.md` | 233 | retain | source only | Stage-by-stage status of the ADW Python harness. Implementation evidence, not a general workflow. |
| `docs/research/software-factory/workflows/matt-pocock/overview.md` | 222 | consolidate | [workflows.md](workflows.md#pocock) | Day-shift / night-shift summary and the human-merge stance. Per-skill mechanism notes and the local skill inventory stay at the source. |
| `docs/research/software-factory/workflows/matt-pocock/course-software-factories.md` | 70 | retain | source only | Public course snapshot: logistics, syllabus, outcomes, employer pitch. |
| `docs/research/software-factory/workflows/poteto/how-she-develops.md` | 484 | consolidate | [workflows.md](workflows.md#poteto) | The reconstruction's shape is in the poteto section. The three walkthroughs stay at the source. |
| `docs/research/software-factory/workflows/poteto/public-workflow.md` | 243 | consolidate | [workflows.md](workflows.md#poteto) | The public principles (trust before parallelism, verification as the limit, gardener) are in the poteto section. Quote and number tables stay at the source. |
| `docs/research/software-factory/workflows/poteto/pstack-mechanics.md` | 694 | consolidate | [workflows.md](workflows.md#poteto) | Overnight contract, non-author verdict, and "a duration is not a finish condition" are in the poteto section. Playbook internals stay at the source. |
| `docs/research/software-factory/workflows/poteto/repos-and-evolution.md` | 495 | consolidate | [workflows.md](workflows.md#poteto) | The lineage is named. Per-repo mechanism (noodle, brainmaxxing, and the rest) stays at the source. |
| `docs/research/software-factory/workflows/poteto/cursor-native-pieces.md` | 611 | consolidate | [workflows.md](workflows.md#poteto) | Recorded as a Cursor layer a factory can use without a custom harness. Component internals and proposed Claude Code stand-ins stay at the source. |
| `docs/research/software-factory/matt-pocock-course/README.md` | 33 | retain | source only | Index of the 2026-11-02 follow-up. The brakes-first overlap is already the design brief. |
| `docs/research/software-factory/matt-pocock-course/adw-adoption-game-plan.md` | 136 | retain | source only | Proposal for filling factory slots on top of ADW. Written as a plan for that repo. |
| `docs/research/software-factory/matt-pocock-course/chief-of-staff-and-companions.md` | 124 | retain | source only | Reading of `chief-of-staff` and its companion skills. Not a workflow this repo uses. |
| `docs/research/software-factory/matt-pocock-course/course-prediction.md` | 157 | retain | source only | Lesson-level prediction, labelled as prediction in the source, for a course date of 2026-11-09. |
| `docs/research/software-factory/matt-pocock-course/github-actions-orchestration.md` | 381 | retain | source only | Reading of Pocock's own Actions repositories, including findings about those repos' identity and retry behaviour. This repo's Actions shape is the design brief. |
| `docs/research/software-factory/matt-pocock-course/skills-pr-catalogue.md` | 517 | retain | source only | Catalogue of 205 pull requests in `mattpocock/skills`. A reference list. |
| `docs/research/software-factory/dissections/TEMPLATE.md` | 34 | retain | source only | Outline for further dissections. Section 7 is porting to Claude Code and ADW. |
| `docs/research/software-factory/dissections/industry/risk-tiered-merge.md` | 406 | retain | source only | Ten-source comparison plus a proposed T0–T3 table and design sketch for ADW. The idea of per-tier human review is already named in [concept.md](concept.md#spectrum). The ADW table is not imported. |
| `docs/research/software-factory/dissections/matt-pocock/software-factory-skill.md` | 256 | retain | source only | Dissection of the upstream glossary skill. Merging it would add a second vocabulary. |
| `docs/research/software-factory/dissections/poteto/dune-contract-agent-friendly-codebase.md` | 185 | retain | source only | Dune rules mapped onto pstack, Pocock, and ADW, including import-graph CI detail. |
| `docs/research/software-factory/dissections/poteto/orchestrate-reconcile-loop.md` | 431 | retain | source only | Queue, exit codes, and stuck detection, written up as an ADW queue-driver design. |
| `docs/research/software-factory/dissections/poteto/overnight-contract.md` | 498 | retain | source only | Bedtime contract written up as an `adw night` design. |
| `docs/research/software-factory/dissections/poteto/shipping-merge-authority.md` | 393 | retain | source only | Non-author verdict bound to `git patch-id`, with a `verdict_check.py` sketch for ADW `ship-gate`. |
| `docs/research/software-factory/dissections/poteto/verification-skill-generator.md` | 417 | retain | source only | Per-app verification skill, written to keep ADW's guarded verifier. |

Line counts are `wc -l` at the pinned commit. 32 paths, matching `find docs/research/software-factory -type f`.

## Other source docs considered

These were in the same docs tree and were classified so the next pass does not re-open them as missed factory material.

| Path | Disposition | Rationale |
|---|---|---|
| `docs/research/enterprise-agent-planes/` | retain | The source README calls this a distinct topic from the software-factory curriculum: an enterprise question-answering diagram, compared with the ADW harness. |
| `docs/research/verification-loop-research.md` | retain | Earlier verification note. The general rule (the author does not hold the oracle) is already in [concept.md](concept.md). The rest is a Spring/Hurl/Playwright design and an ADW verify stage. |
| `docs/research/feedback-loop-practices-research.md` | retain | Earlier survey of feedback-loop practices. The overlapping point (give the agent a check it can run) is in [workflows.md](workflows.md#where-they-agree). |
| `docs/research/seven-phase-workflow-research.md` | retain | Scrutiny of a seven-phase flow against other spec-driven tools, written to decide what entered ADW's practices doc. Copying the phases would add a framework this repo does not use. |
| `docs/research/context-degradation-research.md` | retain | Context-window evidence. Out of scope for the factory record. |
| `docs/factory/README.md` | retain | Operating doc for the factory that is built in claude-code-adw. harness-lab's skeleton is the separate open pull request [harness-lab#3](https://github.com/travism26/harness-lab/pull/3). |
| `docs/factory/github-app-setup.md` | retain | ADW GitHub App setup. Owner setup for this repo belongs with that skeleton, not in this research record. |
| `docs/adr/0001-ticket-driven-runs.md` | retain | ADW decision. This repo's decisions are [docs/adr/](../adr/). |
| `docs/AI_DEVELOPMENT_PRACTICES.md` | retain | ADW living practices doc, partly superseded there by the Claude Code playbook. |
| `docs/DEVELOPMENT_WORKFLOW.md` | retain | ADW spec-to-PR workflow, with that repo's `uv` commands filled in. |
| `docs/agentic-workflow-stack.md` | retain | A different stack (voice, terminal panes, worktree crew) for ADW. |
| `docs/claude-code-playbook/` | retain | Claude Code operating playbook for that repo. Self-contained there, and not the factory concept. |
| `docs/sdlc-agent-map.md` | retain | Proposed catalog of ADW's stage agents. |
| `docs/slim-pipelines-plan.md` | retain | Engineering plan for ADW's slim pipelines. |
| `docs/spec-review-gate-plan.md` | retain | ADW spec-review gate. The source marks it shipped in that repo. |
| `docs/m0-tasks.md`, `docs/m1-tasks.md`, `docs/m2-tasks.md`, `docs/m3-tasks.md`, `docs/m4-results.md`, `docs/m5-results.md`, `docs/m5-tasks.md` | retain | ADW milestone tasks and results. |
| `docs/terminal-foundation-tutorial.md` | retain | ADW terminal tutorial. |
| `docs/agents/` | retain | Issue-tracker and triage instructions for claude-code-adw. This repo has its own [docs/agents/](../agents/). |
| `.claude/skills/`, `skills/progress-log/`, `adws/` | retain | ADW skills and harness code. Not docs for this migration. |

## Checks

Repeatable checks, using a local clone of the source at the pinned commit (here, `/tmp/src-adw`) and Python 3. No extra packages.

1. Coverage and line counts. Every file under `docs/research/software-factory/` is one row of the software-factory table, and the line count matches `wc -l`.
2. Links. Relative links and heading anchors in this folder and in `README.md` resolve. Blob and tree links use the pinned commit and an existing path.
3. Docs only. `git diff --name-only main...HEAD` lists `README.md` and markdown under `docs/software-factory/`.
4. Source untouched. `git -C /tmp/src-adw status --porcelain` is empty, and `git -C /tmp/src-adw rev-parse HEAD` is the pinned commit.

A successful page render is not one of these checks. There is no site build in this repo. The command that encodes checks 1, 2, and 4 is the review note on the pull request, so the result stays with the review instead of being copied into this file and going stale.

## Later source cleanup

None of this change edits claude-code-adw. After this pull request has been reviewed, a later change there could add a pointer from `docs/research/software-factory/README.md` to this folder. Deleting the source corpus would drop the surveys, tables, and ADW sections that this record deliberately did not copy. That pointer is the cleanup worth considering. It is not part of this change.
