# harness-lab

A lab: one repository where a shared software factory builds small projects. Terms used across the lab are here; each project's own terms are in its glossary, listed in [GLOSSARY-MAP.md](GLOSSARY-MAP.md).

## Language

**Lab**:
This repository: one shared factory and the projects it builds.
_Avoid_: Monorepo, platform

**Project**:
One self-contained application under `projects/`, with its own glossary, decisions and check.
_Avoid_: App, module, package

**Factory**:
The GitHub Actions setup that turns labelled issues into draft PRs against this repo, with a review step. It builds the lab's projects, not the harness.
_Avoid_: Pipeline, CI bot, automation

**Ticket**:
A GitHub issue written for the factory to act on.
_Avoid_: Task, story

**Rework round**:
One pass in which the factory revises a draft PR after review. A ticket stops after two.
_Avoid_: Retry, iteration

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

**Switch rule**:
The condition under which the factory's Claude Code moves from the owner's subscription token to an OpenRouter key.
_Avoid_: Fallback, migration
