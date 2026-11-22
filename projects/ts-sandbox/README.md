# ts-sandbox

The Lab's Node.js/TypeScript Sandbox: a small known-good HTTP service whose `check` is the thing being exercised. It exists so verification can be measured on this stack; sibling Sandboxes for Spring and Go use the same Summary shape, so results compare across stacks. It is not a product and not a port of the Gateway. Terms such as Sandbox, Stage, Summary and Pass rate mean what the [glossary](GLOSSARY.md) says.

## Prerequisites

Node.js `^22.18.0 || ^24.0.0` and the npm that ships with it. `package.json` sets this in `engines`, and `.npmrc` has `engine-strict=true`, so any other Node fails `npm ci` and therefore the `install` Stage. Nothing else is needed: no uv, no Go, no global packages.

`npm ci` needs network access to the npm registry. That is the Project's only network use. There are no runtime dependencies; everything in `package.json` is a dev dependency pinned to an exact version.

## Run the service

There is no build step. The service runs as TypeScript through Node's built-in type stripping.

```bash
npm ci
npm start
```

`npm start` runs `node src/main.ts`. The service listens on `127.0.0.1` only, on `PORT` (default `3000`; `0` picks a free port), and prints `ts-sandbox listening on http://127.0.0.1:<port>`.

The one route is `POST /tally`. A body of `{"statuses": ["pass", "fail", "not-run"]}` returns `200` with `{"passed": 1, "total": 3}`.

```bash
curl -s -X POST -d '{"statuses":["pass","fail","not-run"]}' http://127.0.0.1:3000/tally
```

Invalid JSON or a bad `statuses` value returns `400`. A body over 64 KiB returns `413`. Another method on `/tally` returns `405`, and any other path returns `404`. Errors are `{"error": "..."}`.

## Check

Run `./check` from `projects/ts-sandbox/`. It is a bash wrapper around `scripts/check.mjs`. The Stages run in this order:

| Stage | Command |
| --- | --- |
| `install` | `npm ci` |
| `typecheck` | `npx --no -- tsc --noEmit` |
| `lint` | `npx --no -- eslint .` |
| `test` | `npx --no -- vitest run` |

`npx --no` runs only what `npm ci` installed from `package-lock.json`; it never downloads. Every Stage runs even after an earlier one fails, so the Pass rate counts all of them. The exception is `install`: when it fails, the other three cannot run and are marked `not-run`.

`./check --json` prints exactly one JSON object, the Summary, on stdout. All Stage output goes to stderr.

```json
{"project": "ts-sandbox", "stack": "typescript", "stages": [{"name": "<stage>", "status": "pass|fail|not-run", "duration_ms": 0, "command": "<command>"}], "passed": 0, "total": 0}
```

`passed` counts Stages with `pass`. `total` counts all Stages, which is 4.

Exit code `0` means every Stage passed. `1` means any did not. `2` means an unknown argument.

## Planted defects

```bash
node scripts/planted-defects.mjs
```

For each case the script copies the Project (without `node_modules`) to a temp folder, plants one defect, runs that copy's `./check --json`, and exits non-zero unless exactly the expected Stage fails and its output names the defect (for example `TS2322` for the type error). Nothing in the real tree changes and no broken code is committed. Each case runs a real `npm ci`, so it needs the registry (or a warm npm cache) and takes about 20 seconds with a warm cache.

| Planted defect | Expected |
| --- | --- |
| none (baseline) | all four `pass`, exit 0 |
| `package.json` out of sync with the lockfile | `install` fail, the rest `not-run`, exit 1 |
| Node outside `engines` | `install` fail, the rest `not-run`, exit 1 |
| a type error in `src/tally.ts` | only `typecheck` fail, exit 1 |
| an ESLint violation in `src/tally.ts` (`no-explicit-any`) | only `lint` fail, exit 1 |
| a failing vitest test | only `test` fail, exit 1 |

## The verify-ts skill

`.claude/skills/verify-ts/SKILL.md` is a project-scoped Claude Code skill. Start Claude Code in `projects/ts-sandbox/` and type `/verify-ts`, or ask it to run the verify-ts skill. It runs `./check --json` once, reports each Stage's status and the Pass rate, and stops. It edits no file, reads no secrets or environment files, and calls no model or service.

A session started at the repo root does not load the skill at startup. Claude Code loads it once it reads or edits a file under `projects/ts-sandbox/` (see the [skills docs](https://code.claude.com/docs/en/skills)).

## Decisions

- Node is pinned to two majors, 22 and 24, not one. CI's `ubuntu-latest` label is moving from Ubuntu 24.04 (Node.js 22) to Ubuntu 26.04 (Node.js 24), and this Project may not change `.github/` to install its own Node. Anything else fails the `install` Stage.
- npm, not pnpm. npm ships with Node on the runner image, so nothing extra is installed.
- Lint uses typescript-eslint's `recommended` set, which needs no type information. A type error fails `typecheck` alone and a lint violation fails `lint` alone.
- No build step and no runtime dependencies: `node:http` and Node's type stripping. The lockfile holds only the tools the Stages run.
