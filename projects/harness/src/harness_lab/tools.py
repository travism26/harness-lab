"""The harness's tools. Episode 1 has one: read_file, confined to the workspace."""

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ToolResult:
    """Outcome of a tool call: its text, and whether it was refused or failed."""

    output: str
    refused: bool = False
    error: bool = False


def run_read_file(path: str, workspace: Path = WORKSPACE) -> ToolResult:
    """Read a workspace file. A path outside the workspace, or one that cannot be
    resolved, is refused."""
    root = workspace.resolve()
    try:
        target = (root / path).resolve()
    except (OSError, ValueError, RuntimeError) as err:
        return ToolResult(f"Error: cannot resolve path {path!r}: {err}", refused=True, error=True)
    if not target.is_relative_to(root):
        return ToolResult(f"Error: {path!r} is outside the workspace and was refused.",
                          refused=True, error=True)
    if not target.is_file():
        return ToolResult(f"Error: file not found: {path!r}", error=True)
    try:
        return ToolResult(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as err:
        return ToolResult(f"Error: cannot read {path!r}: {err}", error=True)


def read_file(path: str, workspace: Path = WORKSPACE) -> str:
    """Return the file's text, or a message saying why it was refused or failed."""
    return run_read_file(path, workspace).output
