"""The Auditor: report Findings for explicit file or directory paths.

The credential pattern is copied from `CREDENTIAL_RE` in `factory/research_note.py`
(a repo-root path, lines 25-29); this Project does not import `factory`.

The program never executes anything, never opens the network, and never prints
file text or a matched secret.
"""

import argparse
import json
import re
import sys
from pathlib import Path

MAX_BYTES = 1_048_576

Finding = tuple[str, str, int, str]
Findings = set[Finding]
Tokens = list[tuple[int, int, str]]

PHRASES = (
    "ignore the user's question",
    "ignore previous instructions",
    "ignore all previous",
    "ignore the above",
    "disregard the user",
    "do not follow the user",
)
STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
COLON = re.compile(r"\s*:\s*")
COLON_BRACE = re.compile(r"\s*:\s*\{")
SKILL_KEY = re.compile(r"(description|when_to_use):(.*)")

SECRET = re.compile(
    r"sk-(?:ant|or)-|\bsk-[A-Za-z0-9_-]{6,}|gh[pousr]_[A-Za-z0-9]{10,}"
    r"|github_pat_|xox[abposr]-|eyJ[A-Za-z0-9_-]{10,}"
    r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)


def find_root(start: Path) -> Path:
    """Nearest ancestor of `start` (itself included) holding `projects/` and `factory/labels.json`."""
    for candidate in (start, *start.parents):
        if (candidate / "projects").is_dir() and (
            candidate / "factory" / "labels.json"
        ).is_file():
            return candidate
    return start


def display(path: Path, root: Path) -> str:
    """The path relative to `root` with `/` separators, else the path in posix form."""
    try:
        return path.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def read_text(path: Path) -> str | None:
    """The file's text, or None when it is over 1 MiB or holds a NUL byte (a skip)."""
    if path.stat().st_size > MAX_BYTES:
        return None
    data = path.read_bytes()
    if len(data) > MAX_BYTES or b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def scan(text: str, shown: str) -> Findings:
    """The `secret-shaped` Findings of one file's text."""
    return {
        ("secret-shaped", shown, number, "secret")
        for number, line in enumerate(text.split("\n"), start=1)
        if SECRET.search(line)
    }


def tokens(text: str) -> Tokens:
    """Every JSON string literal in `text` as (start, end, decoded text); undecodable ones are dropped."""
    found: Tokens = []
    for match in STRING.finditer(text):
        try:
            decoded = json.loads(match.group())
        except ValueError:
            continue
        found.append((match.start(), match.end(), decoded))
    return found


def line_at(text: str, offset: int) -> int:
    """The 1-based line number of the character at `offset`."""
    return text.count("\n", 0, offset) + 1


def pair_line(text: str, toks: Tokens, key: str, value: str) -> int:
    """The line of the first `"key": "value"` pair, else line 1."""
    for index in range(len(toks) - 1):
        start, end, decoded = toks[index]
        if decoded != key:
            continue
        colon = COLON.match(text, end)
        if colon and toks[index + 1][0] == colon.end() and toks[index + 1][2] == value:
            return line_at(text, start)
    return 1


def key_line(text: str, toks: Tokens, key: str) -> int:
    """The line of the first `"key": {` token, else line 1."""
    for start, end, decoded in toks:
        if decoded == key and COLON_BRACE.match(text, end):
            return line_at(text, start)
    return 1


def named(label: str, value: str) -> str:
    """`label:value`, or just `label` when the value could leak a secret or a phrase."""
    lowered = value.lower()
    unsafe = (
        SECRET.search(value)
        or any(phrase in lowered for phrase in PHRASES)
        or any(char in value for char in "\t\r\n")
    )
    return label if unsafe else f"{label}:{value}"


def has_phrase(text: str) -> bool:
    """True when `text` holds one of the six phrases in any letter case."""
    lowered = text.lower()
    return any(phrase in lowered for phrase in PHRASES)


def is_tool(value: object) -> bool:
    """True for an object with a string `name` and an object `inputSchema`."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("name"), str)
        and isinstance(value.get("inputSchema"), dict)
    )


def tools_under(value: object) -> list[dict[str, object]]:
    """The tools in a `tools` value: a list of tools, a tool, or a dict of tools."""
    if isinstance(value, list):
        return [item for item in value if is_tool(item)]
    if isinstance(value, dict):
        if is_tool(value):
            return [value]
        return [item for item in value.values() if is_tool(item)]
    return []


def find_tools(doc: object) -> list[dict[str, object]]:
    """Every tool the four recognizers see in a parsed document."""
    if not isinstance(doc, dict):
        return []
    tools = [doc] if is_tool(doc) else []
    tools += tools_under(doc.get("tools"))
    result = doc.get("result")
    if isinstance(result, dict):
        tools += tools_under(result.get("tools"))
    servers = doc.get("mcpServers")
    if isinstance(servers, dict):
        for server in servers.values():
            if isinstance(server, dict) and isinstance(server.get("tools"), list):
                tools += tools_under(server["tools"])
    return tools


def schema_texts(value: object) -> list[str]:
    """Every string `description` at any depth inside `value`."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "description" and isinstance(item, str):
                found.append(item)
            else:
                found += schema_texts(item)
    elif isinstance(value, list):
        for item in value:
            found += schema_texts(item)
    return found


def instruction_in_tools(
    tools: list[dict[str, object]], text: str, toks: Tokens, shown: str
) -> Findings:
    """The `instruction-description` Findings of the tools' descriptions and schema texts."""
    found: Findings = set()
    for tool in tools:
        prefix = named("tool", str(tool["name"]))
        texts: list[tuple[str, str]] = []
        if isinstance(tool.get("description"), str):
            texts.append((str(tool["description"]), "description"))
        for key in ("inputSchema", "outputSchema"):
            texts += [(item, "schema") for item in schema_texts(tool.get(key))]
        for item, tail in texts:
            if has_phrase(item):
                line = pair_line(text, toks, "description", item)
                found.add(("instruction-description", shown, line, f"{prefix} {tail}"))
    return found


def scan_json(doc: object, text: str, shown: str) -> Findings:
    """The structured-Rule Findings of a parsed JSON document."""
    toks = tokens(text)
    tools = find_tools(doc)
    found: Findings = set()
    found |= instruction_in_tools(tools, text, toks, shown)
    return found


def is_skill_path(path: Path) -> bool:
    """True for a file named `SKILL.md` or a `*.md` under `.claude/commands`."""
    if path.name == "SKILL.md":
        return True
    if path.suffix != ".md":
        return False
    parts = path.resolve().parts[:-1]
    return any(
        parts[index] == ".claude" and parts[index + 1] == "commands"
        for index in range(len(parts) - 1)
    )


def skill_texts(text: str) -> list[tuple[int, str, str]]:
    """The (line, key, text) of each `description` and `when_to_use` line of the frontmatter."""
    lines = text.split("\n")
    if lines[0] != "---":
        return []
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), len(lines))
    found: list[tuple[int, str, str]] = []
    index = 1
    while index < end:
        match = SKILL_KEY.match(lines[index])
        index += 1
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if value[:1] not in ("|", ">"):
            found.append((index, key, value))
            continue
        while index < end and (not lines[index].strip() or lines[index][0] in " \t"):
            if lines[index].strip():
                found.append((index + 1, key, lines[index]))
            index += 1
    return found


def instruction_in_skill(text: str, shown: str) -> Findings:
    """The `instruction-description` Findings of a skill file's frontmatter."""
    return {
        ("instruction-description", shown, number, f"skill {key}")
        for number, key, item in skill_texts(text)
        if has_phrase(item)
    }


def scan_file(path: Path, text: str, shown: str) -> tuple[Findings, bool]:
    """All Findings of one file's text, and whether a `.json` file failed to parse."""
    found = scan(text, shown)
    if path.name.endswith(".json"):
        try:
            doc = json.loads(text)
        except ValueError:
            return found, True
        if path.name != "scenarios.json":
            found |= scan_json(doc, text, shown)
    if is_skill_path(path):
        found |= instruction_in_skill(text, shown)
    return found, False


def walk(directory: Path) -> list[Path]:
    """Every regular file under `directory`, in sorted order."""
    return sorted(p for p in directory.rglob("*") if p.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m manifest_audit")
    parser.add_argument("--root", help="the directory paths are shown relative to")
    parser.add_argument("paths", nargs="*", metavar="PATH")
    args = parser.parse_args(argv)

    if args.root is not None:
        root = Path(args.root)
        if not root.is_dir():
            print(args.root, file=sys.stderr)
            return 2
        root = root.resolve()
    else:
        root = find_root(Path.cwd().resolve())

    failed: list[str] = []
    files: list[tuple[Path, str | None]] = []
    for given in args.paths:
        path = Path(given)
        if path.is_dir():
            files.extend((p, None) for p in walk(path))
        elif path.is_file():
            files.append((path, given))
        else:
            failed.append(given)

    findings: Findings = set()
    skipped: list[str] = []
    for path, explicit in files:
        shown = display(path, root)
        try:
            text = read_text(path)
        except OSError:
            if explicit is not None:
                failed.append(explicit)
            else:
                skipped.append(shown)
            continue
        if text is None:
            skipped.append(shown)
            continue
        found, unparsed = scan_file(path, text, shown)
        if unparsed and explicit is not None:
            failed.append(explicit)
            continue
        if unparsed:
            skipped.append(shown)
        findings |= found

    if failed:
        for item in failed:
            print(item, file=sys.stderr)
        return 2
    for item in skipped:
        print(item, file=sys.stderr)
    for rule, shown, number, location in sorted(
        findings, key=lambda f: (f[1], f[2], f[0], f[3])
    ):
        print(f"{rule}\t{shown}\t{number}\t{location}")
    return 1 if findings else 0
