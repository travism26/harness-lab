# Lab layout, ticket 2: factory checks each ticket's project with its own check

Part of #16. Lab layout, ticket 2 of 3.

## What to build

Teach the factory which project a ticket is for, and have it test that project with the project's own `check` instead of `uv run pytest`, so the factory can build a project in any language.

## Acceptance criteria

- [ ] `factory/labels.json` has a `project:harness` label, described as owner-applied: it names the project a ticket builds. Adding a project means adding one label here.
- [ ] When building or reworking a ticket, the factory reads its `project:<name>` label. The build prompt names `projects/<name>/` as the project and tells the agent to run `projects/<name>/check` until it passes, plus that project's glossary and decision records.
- [ ] A ticket with no `project:` label, more than one, or a label naming a folder without an executable `check` is refused before any agent runs: the factory comments why on the ticket and removes `ready-for-agent`, the same way `claim` refuses a second in-progress ticket.
- [ ] `docs/factory/README.md` explains the `project:<name>` label and the per-project `check` in "How a Ticket moves".
- [ ] Factory tests cover: the prompt for a labelled ticket, and each refusal case.

## Blocked by

- T1 (lab layout)

