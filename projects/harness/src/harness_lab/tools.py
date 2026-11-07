"""The harness's tools. Episode 1 has one: read_file, confined to the workspace."""

from pathlib import Path

# projects/harness/workspace/, the only folder the tools may read.
WORKSPACE = Path(__file__).resolve().parents[2] / "workspace"

# The tool definition, in Anthropic's tool format.
READ_FILE_TOOL = {
    "name": "read_file",
    "description": "Read a text file from the workspace folder and return its contents.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path of the file, relative to the workspace folder.",
            }
        },
        "required": ["path"],
    },
}

TOOLS = [READ_FILE_TOOL]


def is_refused(path: str, workspace: Path = WORKSPACE) -> bool:
    """True when the path resolves outside the workspace."""
    try:
        return not (workspace.resolve() / path).resolve().is_relative_to(workspace.resolve())
    except (OSError, ValueError, RuntimeError):
        return False


def read_file(path: str, workspace: Path = WORKSPACE) -> str:
    """Return the file's text, or a message saying why it was refused or failed."""
    root = workspace.resolve()
    try:
        target = (root / path).resolve()
    except (OSError, ValueError, RuntimeError) as err:
        return f"Error: cannot resolve path {path!r}: {err}"
    if not target.is_relative_to(root):
        return f"Error: {path!r} is outside the workspace and was refused."
    if not target.is_file():
        return f"Error: file not found: {path!r}"
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        return f"Error: cannot read {path!r}: {err}"
