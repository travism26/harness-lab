# harness-lab

A lab: one repository where a shared software factory builds small projects. Terms used across the lab are here; each project's own terms are in its glossary, listed in [GLOSSARY-MAP.md](GLOSSARY-MAP.md).

## Language

**Lab**:
This repository: one shared factory and the projects it builds.
_Avoid_: Monorepo, platform

**Project**:
One self-contained application under `projects/`, with its own glossary, decisions and check.
_Avoid_: App, module, package

**Project check**:
The one command a Project provides that says whether its code is sound. It is not the Factory check, which proves the factory's credentials work.
_Avoid_: Factory check, test script, verify

**Lab check**:
The one command that says whether the Lab's own code outside any Project is sound.
_Avoid_: root test script, lint script, CI script

**Factory**:
The GitHub Actions setup that turns labelled issues into draft PRs against this repo, with a review step. It builds the lab's projects, not the harness.
_Avoid_: Pipeline, CI bot, automation

**Ticket**:
A GitHub issue written for the factory to act on.
_Avoid_: Task, story

**Goal**:
A planning issue with one destination. The Builder turns it into a Spec and Tickets. It is not a Ticket.
_Avoid_: Epic, initiative

**Spec**:
The agreed design for a Goal. The Factory builds the Tickets cut from it, and does not build the Spec. It is not a Ticket.
_Avoid_: Design doc, proposal

**Rework round**:
One pass in which the factory revises a draft PR after review. A ticket stops after two.
_Avoid_: Retry, iteration

**Review**:
The factory's read of a pull request against its Ticket and the Lab's standards. It ends in a Verdict.
_Avoid_: Code review, judge, second read

**Finding**:
Something a Review reports about a pull request. A Finding either blocks the Verdict or does not.
_Avoid_: Issue, comment, nit

**Verdict**:
The result of a Review for one head commit: PASS or BLOCKED.
_Avoid_: Result, approval, score

**Override**:
The owner's recorded decision to merge a head whose Verdict is not PASS, with the reason written down.
_Avoid_: Bypass, force merge

**Retro**:
A periodic read of recent merged work that proposes new checks and standards for the owner to accept or close.
_Avoid_: Postmortem, audit

**Factory run**:
One attempt of the factory's Implement, Rework, Review or Research workflow that started its agent. A refused Ticket, the CI gate and the Factory check are not Factory runs.
_Avoid_: Run, job, session

**Door**:
Whether merging a change can be cleanly undone: two-way if reverting the merge restores the old state, one-way if not. The agent proposes it; a change that does not state one counts as one-way.
_Avoid_: Reversibility, rollback

**Blast radius**:
How much of the Lab a change can affect: one Project, several Projects, or the shared code. The factory computes it from the changed paths.
_Avoid_: Impact, scope

**Merge danger**:
The Door and the Blast radius of a change, shown together in a factory PR body.
_Avoid_: Risk, danger level

**Run record**:
The one small record a Factory run leaves: what ran, on which Ticket or pull request, how it ended and what it cost. It holds facts and numbers, never text from the model.
_Avoid_: Run log, Call record, ledger row

**Research request**:
A Ticket that states one research question for the factory to answer from public sources.
_Avoid_: Research task, prompt, experiment

**Research note**:
The cited write-up the factory's research path publishes on a draft PR to answer a Research request. It is not a Run record, which holds facts and numbers and never text from the model.
_Avoid_: Report, research result, results file

**Brake**:
A rule that limits what the factory can do on its own, such as draft-only PRs or the rework cap.
_Avoid_: Guardrail, limit

**Stand-in service**:
A tiny fake of a real service, such as an auth server that always grants access, so AI can build and test code against it.
_Avoid_: Mock, stub, fixture

**Setup guide**:
The owner-only, step-by-step instructions for wiring the factory's credentials, ending with a live check.
_Avoid_: Onboarding, runbook

**Factory check**:
The short run that answers the owner's `factory-check` label, proving the factory's credentials work. The live check at the end of the setup guide.
_Avoid_: Smoke test, ping

**Builder**:
The planning bot that turns a goal issue into a spec issue and Tickets. It never starts the factory.
_Avoid_: Planner, Grok bot

**Scout**:
The bot that proposes goal issues for the Builder to plan.
_Avoid_: Researcher, finder

**Switch rule**:
The condition under which the factory's Claude Code moves from the owner's subscription token to an OpenRouter key.
_Avoid_: Fallback, migration

**Bench**:
A fixed set of Bench cases used to compare Setups by the factory's own check and Review.
_Avoid_: Eval, suite, experiment

**Setup**:
The build model, the review model, the factory build prompt, and the harness command a Bench run uses.
_Avoid_: Config, profile, agent

**Bench case**:
One past Ticket recorded as a start commit, the Ticket text from that run, the check command, and the check files whose bytes must still match the start commit.
_Avoid_: Example, fixture, task, Pin

**Bench run**:
One execution of one Bench case under one Setup, in a scratch checkout, which opens no pull request.
_Avoid_: Run, session, job
