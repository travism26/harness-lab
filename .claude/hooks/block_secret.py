"""PreToolUse hook: refuse a shell command that carries a secret-shaped string.

Scans the command text. For `git commit` / `git push` it also scans the added
staged lines. It reports the kind and the place, never the matched text.
"""

import json
import re
import subprocess
import sys

DASHES = "-" * 5
KINDS = (
    ("api-key", re.compile(re.escape("sk-ant-" + "api03-"))),
    ("bearer", re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{20,}")),
    ("pem", re.compile(DASHES + "BEGIN [^-\n]*" + "PRIVATE" + " KEY[^-\n]*" + DASHES)),
)
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
DIFF = [
    "git",
    "diff",
    "--cached",
    "-U0",
    "--no-color",
    "--no-ext-diff",
    "--src-prefix=a/",
    "--dst-prefix=b/",
]


def find_kind(text):
    for kind, pattern in KINDS:
        if pattern.search(text):
            return kind
    return None


def is_commit_or_push(segment):
    tokens = segment.split()
    while tokens and ASSIGNMENT.match(tokens[0]):
        tokens.pop(0)
    if not tokens or tokens[0] != "git":
        return False
    rest = tokens[1:]
    while rest and rest[0].startswith("-"):
        rest.pop(0)
    return bool(rest) and rest[0] in ("commit", "push")


def deny(kind, location):
    reason = f"blocked: {kind} in {location}"
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(out, separators=(",", ":")))
    return 0


def fail(message):
    print(f"block_secret: {message}", file=sys.stderr)
    return 1


def scan_staged(diff):
    path = ""
    in_header = False
    in_hunk = False
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            in_header, in_hunk, path = True, False, ""
        elif in_header and line.startswith("+++ "):
            path = line[4:].removesuffix("\t").strip('"').removeprefix("b/")
        elif line.startswith("@@"):
            in_header, in_hunk = False, True
        elif in_hunk and line.startswith("+"):
            kind = find_kind(line[1:])
            if kind:
                return kind, path
    return None


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        return fail("could not read the tool call")
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return fail("could not read the tool call")

    kind = find_kind(command)
    if kind:
        return deny(kind, "command")

    segments = re.split(r"&&|\|\||;|\n", command)
    if not any(is_commit_or_push(s) for s in segments):
        return 0

    cwd = payload.get("cwd")
    if not isinstance(cwd, str):
        return fail("git diff --cached failed")
    try:
        result = subprocess.run(DIFF, cwd=cwd, capture_output=True, check=False)
    except OSError:
        return fail("git diff --cached failed")
    if result.returncode != 0:
        return fail("git diff --cached failed")
    found = scan_staged(result.stdout.decode("utf-8", errors="replace"))
    if found:
        return deny(found[0], f"staged file {found[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
