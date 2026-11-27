# manifest-audit

A static review of local files. The Auditor reads the files you name and prints a Finding for each line a Rule matches.

## Run

```
uv run --package manifest-audit python -m manifest_audit [--root ROOT] PATH ...
projects/manifest-audit/check
```

`PATH` is a file or a directory (walked recursively). `ROOT` defaults to the nearest ancestor of the current directory holding `projects/` and `factory/labels.json`, otherwise the current directory.

## Output

One line per Finding on stdout, tab-separated: `rule-id`, `path`, `line`, `location`. Paths are relative to `ROOT` when the file is under it. Files that are skipped (over 1 MiB, or containing a NUL byte) are named on stderr.

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
