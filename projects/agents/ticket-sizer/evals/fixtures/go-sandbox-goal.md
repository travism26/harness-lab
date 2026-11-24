# Goal: Go sandbox Project with a JSON-reporting check and a verify-go skill for Claude Code

## For you

**What.** A local factory environment for one stack: a small Go HTTP service (one handler and one domain package) in `projects/go-sandbox/`, with `go.mod` and `go.sum`, with an executable `projects/go-sandbox/check` that runs `gofmt`, `vet`, `staticcheck` (pinned as a `tool` dependency) and `test` against locked dependencies, plus one Claude Code skill, `projects/go-sandbox/.claude/skills/verify-go/SKILL.md`, that runs the check and reports a pass rate. It is one of three sibling Goals (Spring, Go, Node.js/TypeScript), each a separate Project with the same report format, so results compare across stacks.

**Done looks like.** `projects/go-sandbox/check` passes on `main` in CI; `./check --json` prints one summary with each stage's status and the pass rate; each stage is shown failing on a planted defect; and `/verify-go` in a Claude Code session started in `projects/go-sandbox/` runs it and reports the result.

## For the agent

**Destination.** `projects/go-sandbox/`, a new Project:
- the service code and its tests;
- an executable `check` (stages, in order: `gofmt`, `vet`, `staticcheck`, `test`). It runs every stage even after one fails and exits non-zero if any stage failed. With `--json` it prints one JSON object to stdout with each stage's name, status, duration and command, and the passed and total counts;
- `projects/go-sandbox/.claude/skills/verify-go/SKILL.md`: a project-scoped Claude Code skill that runs `./check --json`, reports each stage and the pass rate, and stops;
- `projects/go-sandbox/README.md` and `projects/go-sandbox/GLOSSARY.md`, with its line added to `GLOSSARY-MAP.md`.

**Dependencies and runtime.** `go.sum` committed, linters pinned as `tool` dependencies in `go.mod` and run with `go tool`.

**Out of scope.** Scoring any gateway with this skill. The Spring and Node.js/TypeScript sandboxes.
