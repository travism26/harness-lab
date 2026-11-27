# Rules

## instruction-description

Reports a tool or skill description that holds an instruction aimed at the model. The match is a case-insensitive substring of one of six phrases (the apostrophe is ASCII):

- `ignore the user's question`
- `ignore previous instructions`
- `ignore all previous`
- `ignore the above`
- `disregard the user`
- `do not follow the user`

Single words such as `ignore`, `instead` and `system` are not phrases.

Where it looks:

- A tool is an object with a string `name` and an object `inputSchema`. Tools are read at the top level of the file, in a top-level `tools` list or object, in `result.tools`, and in the `tools` list of each `mcpServers` entry. Nothing else is searched.
- A tool's own string `description`, and any string `description` nested at any depth inside its `inputSchema` or `outputSchema`.
- A skill file is a file named `SKILL.md`, or a `*.md` file under a `.claude/commands` directory, whose first line is exactly `---`. The Rule reads the frontmatter keys `description` and `when_to_use`, written on one line or as a `|` or `>` block. The markdown body is not read.
- A file named `scenarios.json` is scanned for `secret-shaped` only.

Locations: `tool:<name> description`, `tool:<name> schema`, `skill description`, `skill when_to_use`. When a tool name matches the credential expression, holds one of the phrases in any letter case, or holds a tab, CR or LF, the location says `tool` and omits the name.

Line: for a tool, the first place in the file where a `"description"` key is followed by that exact text; line 1 if none is found. For a skill, the line holding the text. A tool seen by several recognizers is one Finding. The matched phrase is never printed.

## hook-worktree-exec

Reports a Claude Code hook command that runs a worktree path. The Auditor never runs the command.

A handler is an object whose `type` is absent or `command` and whose `command` is a string. Handlers of type `http`, `mcp_tool`, `prompt` and `agent` do not match, but their file is still scanned for `secret-shaped`. Handlers are read from an event map: event name to a list, each item either a group holding a `hooks` list of handlers or a handler itself.

- In any `.json` file that is not a plugin manifest, the event map is the top-level `hooks` object (the shape of `settings.json` and `hooks/hooks.json`). An `mcpServers` command is not a hook.
- A plugin manifest is a `plugin.json` whose parent directory is `.claude-plugin`; the plugin root is that directory's parent. Its `hooks` may be a string path, an inline event map (a lone `hooks` wrapper is unwrapped), or a list mixing both.

A handler matches when either test holds. A relative-path token is one with no `://` that starts with `./` or `../`, or contains a `/` and does not start with `/`.

1. A whitespace-separated token of `command`, with surrounding `'` and `"` removed, contains `CLAUDE_PROJECT_DIR` or `CLAUDE_PLUGIN_ROOT` (the bare name, so `${CLAUDE_PROJECT_DIR}` and `$CLAUDE_PROJECT_DIR` both match), or is a relative-path token.
2. `args` is a list, `command` with surrounding whitespace removed is one of `bash`, `sh`, `zsh`, `dash`, `powershell`, `pwsh`, `cmd` or `powershell.exe`, and a token of any string argument meets test 1.

So `python3` or `node` with a worktree script as an argument is not this Rule. The tests are literal: a shell-form command such as `echo hi 2>/dev/null` matches, because `2>/dev/null` contains `/` and does not start with `/`.

Plugin paths: a string path is resolved against the plugin root. When it resolves outside the root, or the file is missing, the path is named on stderr as a skip, the exit code does not change and the file is not opened. A target inside the root, and `<plugin root>/hooks/hooks.json` when it exists, are each scanned as files in their own right and their Findings carry their own path. A file reached twice is scanned once.

Location: `hooks command`. Line: the first place in the file where a `"command"` key is followed by that exact command text; line 1 if none is found.

## secret-shaped

Reports a line of a scanned file that matches the credential expression. The location is `secret`. The matched text is never printed.

The expression is `CREDENTIAL_RE` at `factory/research_note.py` lines 25-29. This Project holds its own copy and does not import `factory`; a test checks the copy has not drifted.

Findings are heuristic, and a clean scan is not a security guarantee.
