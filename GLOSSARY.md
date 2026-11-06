# harness-lab

A small agent harness, built in public by a software factory, with one blog post per episode.

## Language

**Harness**:
The small program in this repo that runs a model in a tool loop. It is the thing the series teaches.
_Avoid_: Agent framework, bot

**Factory**:
The GitHub Actions setup that turns labelled issues into draft PRs against this repo, with a review step. It builds the harness.
_Avoid_: Pipeline, CI bot, automation

**Episode**:
One numbered stage of the series (0 to 5), delivered as a set of tickets and one post.
_Avoid_: Chapter, part, milestone

**Post 0**:
The first episode, which sets up the factory through the skeleton PR.
_Avoid_: Bootstrap post, intro

**Post**:
The blog article for an episode, written in the author's voice in the separate blog repo.
_Avoid_: Article, write-up

**Episode notes**:
The file the factory writes in this repo when an episode finishes: what was built, what broke, key snippets, PR links. Source material for the post.
_Avoid_: Changelog, summary

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
