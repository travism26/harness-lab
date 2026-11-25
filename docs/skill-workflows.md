# Skill workflows for the Lab: a brainstorm

A brainstorm from November 2026, kept for reference. Nothing here is wired up yet: trees, scenarios and ways to enforce them.
Diagram version: `docs/skill-workflows.html`.

## How to use this file

- This is a proposal, not an enforced rule. Nothing checks that you followed it.
- Most skills named here are user-only, so an agent cannot invoke them itself. Only a person typing the command can.
- Pick the scenario in "Scenarios" that matches the work.
- Follow its flow in order.
- Record a skipped step as `skip: <reason>`.
- Treat a step as done only when its proof exists.

## Legend

Tags used on steps below:

- `[M]` Matt Pocock skill
- `[L]` Lauren Tan (pstack) skill
- `[X]` Lab mechanism (check, CI, factory Review, human merge)
- `[A]` Artifact (proof a step leaves behind)
- `(optional)` marks a dashed-border (optional) step

## 1. The two pure trees

### Diagram 1A: Matt Pocock: tracker-first

Main line:

1. `[M]` `/grill-with-docs`: interview; writes GLOSSARY and ADRs
2. `[M]` `/to-spec`: writes up the conversation, agrees test seams, publishes with `ready-for-agent`
3. `[M]` `/to-tickets`: vertical-slice tickets with blocking edges; owner approves
4. `[M]` `/implement-spec`: one subagent per ready ticket, each in a worktree
5. Per ticket (group), in order:
   1. `[M]` `tdd`
   2. `[M]` `code-review`: standards + spec, in parallel
   3. `[M]` commit
6. `[M]` `/handoff`, `/retro`

Branches:

- `prototype` (throwaway, branch never merged) hangs off step 1 and goes back to grilling.
- `/triage` (incoming issues: label state machine) hangs off step 2.
- `/wayfinder` (huge work: a map of decision tickets, plans, does not build) hangs off step 3.
- `diagnosing-bugs` (build a pass/fail feedback loop first) hangs off per-ticket `tdd`.

Strength: the tracker is the source of truth; every step leaves an issue, a label or a doc.
Gap: nothing drives the running app to prove behaviour.

### Diagram 1B: Lauren Tan (pstack): playbook-first

Main line:

1. `[L]` `/poteto-mode`: picks a playbook, copies its steps into the todo list
2. `[L]` `/sharpen` (optional)
3. `[L]` `/how` / `/why`: how it works now, and why
4. `[L]` `/architect`: plus `/arena` for competing designs
5. `[L]` build by subagent: `/tdd` when a cheap test path exists
6. `[L]` `/verify-<app>`: made once by `/create-verification-skill`; drives the real app
7. `[L]` `/unslop`, `/no-comments`
8. `[L]` `/interrogate` (optional): multi-model review, only if contested
9. `[L]` open PR
10. `[L]` babysit
11. `[L]` ship

Branches:

- `/figure-it-out` (large or unattended: phases) then `/show-me-your-work` (a `decisions.tsv` log) replaces the main line's front half. Both hang off step 1.
- `/blast-radius` (small diff you don't trust) joins before step 9, open PR.
- `/correct`, `/reflect` come after step 11, ship: turn repeated mistakes into checks / skill edits.

Strength: proof. Verdicts are VERIFIED / NOT VERIFIED / INCONCLUSIVE, the judge is never the author, skipped steps stay listed as `skip: <reason>`.
Gap: no tracker pipeline, no triage, no glossary discipline.

### Where they overlap

| Job | Matt | Lauren |
| --- | --- | --- |
| sharpen an idea | `grilling` | `/sharpen` |
| design | `codebase-design` | `/architect` + `/arena` |
| test-first | `tdd` | `/tdd` |
| review | `code-review` | `/interrogate` |
| prototype | `prototype` | Prototype playbook |
| learn from mistakes | `/retro` | `/correct`, `/reflect` |
| large work | `/wayfinder`, `/to-tickets` | `/figure-it-out` |

- **Only Matt:** spec and ticket pipeline, triage state machine, glossary and ADRs, `/handoff`.
- **Only Lauren:** verification skills, decision log, cross-model judging, PR babysit and ship, `/how` / `/why`.

## 2. Hybrids

### Diagram 2A: Hybrid A: tracker front, proof back (the default candidate)

1. `[M]` `/grill-with-docs`
2. `[M]` `/to-spec`
3. `[M]` `/to-tickets`
4. Per ticket (group), in order:
   1. `[L]` `/architect`
   2. `[M]` build with `tdd` (delegated)
   3. `[X]` `projects/<name>/check`
   4. `[L]` `/verify-<project>`
   5. `[M]` `code-review`
   6. `[L]` `/interrogate` (optional): only when risky
5. `[X]` PR
6. `[X]` CI + factory Review
7. `[X]` human merge

Branches:

- `[L]` `/correct` (when a mistake repeats) comes after step 7.

Matt owns intake and the tracker. Lauren owns design and proof. The Lab's check, CI and Review stay the gate.

### Diagram 2B: Hybrid B: factory lane (unattended, in CI)

1. `[X]` Ticket started by `factory:start` after `owner:implement`
2. `[X]` factory agent: only skills committed in the repo
3. `[X]` `projects/<name>/check`
4. `[L]` `/verify-<project>`: committed under the Project
5. `[A]` workflow record in the PR
6. `[X]` CI
7. `[X]` factory Review
8. `[X]` human merge

Branches:

- `[X]` rework (max 2 rounds, back to the factory agent) hangs off step 7.

The factory runner has no home-folder skills. Anything it must follow has to be committed in the repo.

### Diagram 2C: Hybrid C: overnight on the laptop

1. `[M]` `/wayfinder` map: or a ticket queue
2. `[L]` `/figure-it-out` contract: goal, done means, fresh worktree, escape hatch
3. `[A]` `/show-me-your-work` `decisions.tsv`
4. `[M]` per ticket: as Hybrid A's build half
5. `[M]` morning audit: `code-review` by a different model
6. `[X]` human merge

## 3. Scenarios

One flow per scenario. Lines are shown only where the brief gave them.

| Scenario | Use when | Flow in one line | Proof |
| --- | --- | --- | --- |
| Small ticket | one file or one clear fix | `/implement` (`tdd`) → check → `code-review` or `/blast-radius` → merge | green check, one review |
| Medium ticket | one Project, a handful of files (the go-sandbox Goal, #174, was this size) | `/sharpen` or a short `grilling` → `/architect` → build with `tdd` (delegated) → check → `/verify-<project>` → `code-review` → PR | check, verify Summary, Review PASS |
| Big ticket | several PRs or more than one Project | `/grill-with-docs` → `/to-spec` → `/to-tickets` → `/implement-spec` (per ticket) → `/interrogate` (before merge) → `/correct` (after) | spec, tickets with blocking edges, per-ticket check and review |
| Huge or unknown shape | more than one session can hold | `/wayfinder` map → research / prototype / grilling tickets → becomes a Big ticket | the map issue and its resolved decision tickets |
| POC / Experiment | testing a claim or a shape | Experiment request (`experiments/<slug>/request.md`) → throwaway branch → `results.md` → keep or drop → if kept, re-enter as a Medium ticket | `results.md`, recorded whether it passed or failed |
| Bug | not stated | `diagnosing-bugs` → failing test (`tdd`) → fix → check → `/correct` (optional, if it is a repeat) | the test that failed before and passes after |
| Unattended run | not stated | Hybrid C (section 2, Diagram 2C) → `decisions.tsv` plus the morning audit | `decisions.tsv` plus the morning audit |

### Small ticket

Flow: `/implement` (`tdd`) → check → `code-review` or `/blast-radius` → merge
- Use when: one file or one clear fix.
- Skip: grilling, spec, architect.
- Proof: green check, one review.

### Medium ticket

Flow: `/sharpen` or a short `grilling` → `/architect` → build with `tdd` (delegated) → check → `/verify-<project>` → `code-review` → PR
- Use when: one Project, a handful of files (the go-sandbox Goal, #174, was this size).
- Skip: to-tickets, arena.
- Proof: check, verify Summary, Review PASS.

### Big ticket

Flow: `/grill-with-docs` → `/to-spec` → `/to-tickets` → `/implement-spec` (per ticket) → `/interrogate` (before merge) → `/correct` (after)
- Branch: `/architect` + `/arena` on the contested ticket, hanging off `/implement-spec`.
- Use when: several PRs or more than one Project.
- Skip: nothing.
- Proof: spec, tickets with blocking edges, per-ticket check and review.

### Huge or unknown shape

Flow: `/wayfinder` map → research / prototype / grilling tickets → becomes a Big ticket
- Artifact off `/wayfinder` map: the map issue and its resolved decision tickets.
- Use when: more than one session can hold.
- Proof: the map issue and its resolved decision tickets.

### POC / Experiment

Flow: Experiment request → throwaway branch → `results.md` → keep or drop → if kept, re-enter as a Medium ticket
- Experiment request is `experiments/<slug>/request.md`: a claim, pass/fail checks, cost cap.
- Branch: `prototype` can stand in for the Experiment request ("or").
- Use when: testing a claim or a shape.
- Skip: review, merge.
- Proof: `results.md`, recorded whether it passed or failed.

### Bug

Flow: `diagnosing-bugs` (feedback loop first) → failing test (`tdd`) → fix → check → `/correct` (optional, if it is a repeat)
- Proof: the test that failed before and passes after.

### Unattended run

Flow: Hybrid C (section 2, Diagram 2C) → `decisions.tsv` plus the morning audit
- Proof: `decisions.tsv` plus the morning audit.

## 4. How a workflow could be enforced

You cannot prove an agent used a skill. You can require the artifact that step leaves behind. So define each step by its artifact.

### Enforcement ladder

Strongest at the top, weakest at the bottom.

1. Written convention: advisory
2. Router skill: soft
3. Workflow record: checkable
4. Mechanical gate: hard
5. Claude Code hooks: hard, in-session
6. Agents in `projects/agents/`: independent judge

Listed here from rung 1 up to rung 6 (strength rises with the number).

| Rung | What it is | Works on laptop | Works in the factory | Strength |
| --- | --- | --- | --- | --- |
| 1. Written convention | a scenario-to-skills table in `CLAUDE.md` | yes | read only | advisory |
| 2. Router skill | one skill committed in the repo (for example `/workflow <scenario>`) that copies the scenario's steps into the todo list; a skipped step stays as `skip: <reason>`; built as `.claude/skills/workflow/SKILL.md` | yes | yes | soft |
| 3. Workflow record | each PR carries a small record: scenario, each step done or skipped with a reason, a link to its evidence | yes | yes | checkable |
| 4. Mechanical gate | a script in CI reads the record and fails when a required step has no evidence; factory Review treats a missing step as a blocker; uses the existing rework rounds | yes | yes | hard |
| 5. Claude Code hooks | committed project settings: a Stop hook that refuses to finish until the check ran, a PreToolUse hook that blocks `git push` until the record exists | yes | yes (the factory loads project settings) | hard, in-session |
| 6. Agents in `projects/agents/` | small Agent SDK programs with a fixed tool list and a strict output schema, run beside the work | by hand today | not wired yet | independent judge |

### Three constraints found in the repo

- (a) Almost every skill in both suites is user-only (`disable-model-invocation`), so an agent cannot invoke them; only a person typing the command can.
- (b) The factory runner installs plain Claude Code with project settings only: no plugins, no home-folder skills, and the repo has no root `.claude/` folder yet.
- (c) Agents in `projects/agents/` load no skills (`settingSources: []`), run on Haiku 5.5, cap at $1 a run and are launched by hand.

## 5. Agent ideas (not built)

- `ticket-sizer`: reads an issue, proposes a scenario (small, medium, big, huge, POC, bug) through a strict schema. Code checks the answer against the allowed list. Feeds rung 2 and 3.
- `workflow-auditor`: read-only. Reads a PR and its workflow record, answers pass or fail per required step with the evidence it found. Feeds rung 4. Never the agent that wrote the change.
- `verify-runner`: runs a Project's `./check --json`, returns the Summary unchanged. The three sandboxes already give it a shared format.

With a workflow record on every PR, the Lab can run the same Bench case under Matt's tree, Lauren's tree and a hybrid, and compare passed out of N. That is how we test them ourselves.

## 6. Open questions for the owner

1. Is Hybrid A the default, or do you want to run the two pure trees side by side first?
2. Which scenario do we wire first? Suggested: Medium ticket.
3. How far up the ladder for a first cut? Suggested: rungs 2 to 4.
4. Vendor skills into the repo for the factory, or keep the factory on Lab-written skills only? pstack is MIT; Matt Pocock's licence is not checked yet.
5. Are `ticket-sizer` and `workflow-auditor` worth a Goal in `projects/agents/`?
