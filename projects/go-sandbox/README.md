# go-sandbox

The Sandbox is a small Go HTTP service kept correct on purpose, with a check that reports each Stage and the Pass rate. It is a fixture for measuring verification on the Go stack, in the same Summary format the other stacks' sandboxes use. Terms such as Stage, Summary and Planted defect mean what the [glossary](GLOSSARY.md) says.

The service has one endpoint and one domain package. `GET /pass-rate?passed=3&total=4` returns `{"passed":3,"total":4,"percent":75}`, and a pair that is not a valid Pass rate (`passed=5&total=4`, `total=0`) gets a 400.

## Prerequisites

- Go 1.27.3 or newer on `PATH`, the version `projects/go-sandbox/go.mod` names.
- A C compiler, because `go test -race` needs cgo.
- Network on the first run, when Go downloads the modules locked in `projects/go-sandbox/go.sum`.

## Check

```bash
./check
```

It runs four Stages in order and prints a table and `passed N of 4`:

| Stage | Command |
|---|---|
| `gofmt` | `gofmt -l .` |
| `vet` | `go vet ./...` |
| `staticcheck` | `go tool staticcheck ./...` |
| `test` | `go test -race -count=1 ./...` |

Every Stage runs even after an earlier one failed, so the Pass rate counts all four. `gofmt -l .` exits 0 even when it lists files, so the `gofmt` Stage fails when it lists any. A Stage is `not-run` only when its tool (`gofmt` or `go`) is not on `PATH`. The exit code is 0 only when all four passed.

```bash
./check --json
```

prints the Summary, one JSON object on one line of stdout, and sends all tool output to stderr:

```json
{"project": "go-sandbox", "stack": "go", "stages": [{"name": "gofmt", "status": "pass", "duration_ms": 7, "command": "gofmt -l ."}, {"name": "vet", "status": "pass", "duration_ms": 100, "command": "go vet ./..."}, {"name": "staticcheck", "status": "pass", "duration_ms": 199, "command": "go tool staticcheck ./..."}, {"name": "test", "status": "pass", "duration_ms": 1397, "command": "go test -race -count=1 ./..."}], "passed": 4, "total": 4}
```

## The verify-go skill

`projects/go-sandbox/.claude/skills/verify-go/SKILL.md` is a Claude Code skill scoped to this Project. Start Claude Code in this folder and type:

```
/verify-go
```

Claude runs `./check --json` once, reports each Stage's status and the Pass rate, and stops. The skill edits nothing, reads no secrets and calls no model or service. A session started at the repo root can load the skill once Claude has worked on a file in this folder.

## Planted defects

```bash
./planted-defects
```

For each Stage it copies the Project to a temporary folder, adds one Planted defect there as a new file in `internal/passrate/` (an unformatted file, a lock copied by value, an unused function, a failing test), runs `./check --json` in the copy and compares the result with what that defect should cause. It prints one table row per case and exits 0 only when every row says `ok`. Nothing is written to this folder.

The `vet` defect is a lock copied by value and not a bad Printf verb, because a bad Printf verb would fail three Stages: staticcheck and the vet subset that `go test` runs report it too.

## Run the service

```bash
go run ./cmd/go-sandbox
curl 'http://127.0.0.1:8080/pass-rate?passed=3&total=4'
```

It listens on loopback only (`projects/go-sandbox/cmd/go-sandbox/main.go`).

## Dependencies

The service uses the standard library only. staticcheck v0.8.2 is the one `tool` dependency in `projects/go-sandbox/go.mod`, run with `go tool`. To change it, then commit `go.mod` and `go.sum` together:

```bash
go get -tool honnef.co/go/tools/cmd/staticcheck@<version>
go mod tidy
```

The check sets `GOFLAGS=-mod=readonly`, so a module missing from `go.sum` fails the Stage instead of being added.

golangci-lint is left out. Pinned as a `tool` (v2.15.0) it adds 211 indirect requirements to `go.mod`, shares one module graph with staticcheck, and by default runs `govet` and `staticcheck` again, so one defect would fail two Stages.
