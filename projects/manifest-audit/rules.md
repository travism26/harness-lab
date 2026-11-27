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

## secret-shaped

Reports a line of a scanned file that matches the credential expression. The location is `secret`. The matched text is never printed.

The expression is `CREDENTIAL_RE` at `factory/research_note.py` lines 25-29. This Project holds its own copy and does not import `factory`; a test checks the copy has not drifted.

Findings are heuristic, and a clean scan is not a security guarantee.
