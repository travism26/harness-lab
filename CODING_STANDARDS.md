# Coding standards

These rules apply across the Lab. The factory's builder follows them, and its reviewer checks against them.

## Projects and dependencies

- **Every Python project is a uv workspace member.** It is listed in the root manifest's workspace members and its dependencies, and locked in the one root `uv.lock`. A project in another language commits its own lockfile (for Go, `go.sum`).
- **A project's `check` runs against committed, locked dependencies only, and exits non-zero on failure.** For a Python project, that means `uv run --locked --package <name> pytest` from the project folder.
- **Every manifest, config file and setting is read by something.** Add one when the code that reads it lands, in the same change.
- **Package and module names are unique across the Lab.**

## Paths and moves

- **Comments and docs name other files by their repo-root path** (for example `projects/harness/docs/adr/0002-…`), so a search finds every reference when a file moves.
- **A move includes rewording.** When a change moves content, update the sentences that say where that content lives, as well as the links. That rewording is part of the move, so the reviewer judges it as in scope.
