"""Run a named check and, only when it passes, record a marker for a session.

Usage: python3 .claude/hooks/record_check.py <session_id> <selector>

The selector is `factory` or `project:<name>`. The marker
`<root>/.claude/check-passed/<session_id>` holds `passed <selector>` and nothing
the check printed. It never echoes the session id or the selector.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
PROJECT_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
FACTORY = ["uv", "run", "pytest", "tests/factory"]


def fail(message, code=2):
    print(f"record_check: {message}", file=sys.stderr)
    return code


def project_check(root, name):
    directory = root / "projects" / name
    check = directory / "check"
    if not check.is_file():
        return None
    try:
        inside = check.resolve().is_relative_to(directory.resolve())
    except (OSError, RuntimeError):
        return None
    return check if inside else None


def argv_for(root, selector):
    if selector == "factory":
        return list(FACTORY)
    prefix = "project:"
    if selector.startswith(prefix) and PROJECT_NAME.fullmatch(selector[len(prefix) :]):
        check = project_check(root, selector[len(prefix) :])
        if check is not None:
            return [str(check)]
    return None


def main():
    args = sys.argv[1:]
    if len(args) != 2:
        return fail("usage: record_check.py <session_id> <selector>")
    session_id, selector = args
    if not SESSION_ID.fullmatch(session_id):
        return fail("the session id must be letters, digits, _ and -")
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    root = Path(project_dir) if project_dir else Path(__file__).resolve().parents[2]
    argv = argv_for(root, selector)
    if argv is None:
        return fail("unknown selector")
    try:
        result = subprocess.run(argv, cwd=root, check=False)
    except OSError:
        return fail("the check could not be started", 1)
    if result.returncode != 0:
        return result.returncode if result.returncode > 0 else 1
    marker_dir = root / ".claude" / "check-passed"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / session_id).write_text(f"passed {selector}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
