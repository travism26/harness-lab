# manifest-audit

A static review of local files. The Auditor reads the files you name and prints a Finding for each line a Rule matches.

## Run

```
uv run --package manifest-audit python -m manifest_audit [--root ROOT] [PATH ...]
projects/manifest-audit/check
```

`ROOT` defaults to the nearest ancestor of the current directory holding `projects/` and `factory/labels.json`, otherwise the current directory.

With no `PATH` the Auditor discovers files from `ROOT`: every file under a `.claude` directory, every `.claude-plugin/plugin.json`, every `.mcp.json`, and every file named like `mcp*.json` or `*mcp*manifest*` (case-sensitive). It skips `.git` and `node_modules` anywhere, the top-level `work` and `run-out`, `projects/manifest-audit/fixtures`, and any nested checkout (a directory other than `ROOT` holding a `.git` entry).

With a `PATH` (a file or a directory) the Auditor scans exactly that. A directory is walked in full, with no name filter and no skipped directories, so passing the checkout root reads files that discovery never opens, and passing `fixtures/` reads the synthetic samples.

## Output

One line per Finding on stdout, tab-separated: `rule-id`, `path`, `line`, `location`. Paths are relative to `ROOT` when the file is under it. Files that are skipped (over 1 MiB, or containing a NUL byte), and `.json` files found while walking or discovering that do not parse, are named on stderr.

Exit codes:

- `0`: no Findings.
- `1`: one or more Findings.
- `2`: a usage or input error (an unknown argument, a missing `ROOT` or `PATH`, or an explicit `.json` file that does not parse). Stdout is empty.

## Rules

- `instruction-description`: a tool or skill description that holds an instruction aimed at the model.
- `url-and-file`: a tool whose input schema has an unconstrained URL property and a file property.
- `hook-worktree-exec`: a hook command that runs a worktree path, found in settings, hooks and plugin files.
- `secret-shaped`: a line that looks like it holds a credential.

See `projects/manifest-audit/rules.md`.

## Limits

Findings are heuristic: a match is a hint, not proof. Put plainly: a clean scan is not a security guarantee.

The program does not execute hooks or start servers, and makes no model or network call. It never prints file text or a matched secret.

## Factory eligibility

The `project:manifest-audit` row is in `factory/labels.json`, and the Factory can take a Ticket for this Project once that label is synced to GitHub.
