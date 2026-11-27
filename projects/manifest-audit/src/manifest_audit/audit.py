"""The Auditor: report `secret-shaped` Findings for explicit file or directory paths.

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


def scan(text: str, shown: str) -> set[tuple[str, str, int, str]]:
    """The `secret-shaped` Findings of one file's text."""
    return {
        ("secret-shaped", shown, number, "secret")
        for number, line in enumerate(text.split("\n"), start=1)
        if SECRET.search(line)
    }


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

    findings: set[tuple[str, str, int, str]] = set()
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
        if explicit is not None and path.name.endswith(".json"):
            try:
                json.loads(text)
            except ValueError:
                failed.append(explicit)
                continue
        findings |= scan(text, shown)

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
