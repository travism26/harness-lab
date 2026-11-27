"""Stop hook: hold a session open until a passing check is recorded for it.

Opt-in: with HARNESS_LAB_REQUIRE_CHECK unset or not exactly `1` it does nothing.
Otherwise it looks for `<root>/.claude/check-passed/<session_id>` whose first line
starts with `passed `, and blocks the stop when there is none. It never writes a
file and never echoes the hook input.
"""

import json
import os
import re
import sys
from pathlib import Path

SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
REFUSED = (
    "HARNESS_LAB_REQUIRE_CHECK=1 and the Stop hook input was refused: "
    "it is not a JSON object with a session id of letters, digits, _ and -."
)
MISSING = (
    "HARNESS_LAB_REQUIRE_CHECK=1 and no passing check marker for this session. "
    "Run python3 .claude/hooks/record_check.py {session_id} factory or project:<name>."
)


def block(reason):
    out = {"decision": "block", "reason": reason}
    print(json.dumps(out, separators=(",", ":")))
    return 0


def has_passed(marker):
    try:
        if not marker.is_file():
            return False
        text = marker.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False
    return text.split("\n", 1)[0].startswith("passed ")


def main():
    if os.environ.get("HARNESS_LAB_REQUIRE_CHECK") != "1":
        return 0
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        return block(REFUSED)
    if not isinstance(payload, dict):
        return block(REFUSED)
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        return block(REFUSED)
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd")
    if not isinstance(root, str) or not root:
        return block(REFUSED)
    if has_passed(Path(root) / ".claude" / "check-passed" / session_id):
        return 0
    return block(MISSING.format(session_id=session_id))


if __name__ == "__main__":
    sys.exit(main())
