"""Freeze the number of counted `#` comment lines in tracked Python files.

The Lab check fails when a change adds a counted comment line to a tracked `.py` file. The
baseline in `factory/comment_baseline.txt` holds one `path count` line per file with at least one
counted line. A working-tree count above its baseline fails. A baseline above that path's count
on the default branch (`main` when `refs/heads/main` exists, otherwise `origin/main`) fails too,
so a branch cannot raise the ceiling. Deleting counted lines is always allowed.

Run `uv run python -m factory.comment_ratchet update` from the repo root to write the lower
baseline. It refuses a rise: it exits 1 and leaves the baseline file untouched.
"""

import argparse
import io
import re
import subprocess
import sys
import tokenize
from collections.abc import Iterable, Mapping
from pathlib import Path

BASELINE = Path("factory") / "comment_baseline.txt"
DEFAULT_BRANCH = "main"

_COOKIE = re.compile(r"coding[:=]\s*[-\w.]+")
_DIRECTIVES = (
    re.compile(r"noqa(:\s*[A-Z][0-9]+(\s*,\s*[A-Z][0-9]+)*)?"),
    re.compile(r"type: ignore(\[[^\]]*\])?"),
    re.compile(r"pragma:\s*\w+(\s+\w+)?"),
)
_READ_ERRORS = (tokenize.TokenError, SyntaxError, UnicodeDecodeError, ValueError)


class RatchetError(Exception):
    """A condition that fails the check, with a message naming what is wrong."""


def is_excluded(line: int, text: str, source_line: str) -> bool:
    """Whether a comment token is not counted. `text` is the token including the `#`."""
    if line == 1 and text.startswith("#!"):
        return True
    if line <= 2 and source_line.lstrip().startswith("#") and _COOKIE.search(text):
        return True
    body = text[1:].strip()
    return any(pattern.fullmatch(body) for pattern in _DIRECTIVES)


def _normalize(text: str) -> str:
    body = text[1:]
    body = body.removeprefix(" ")
    return body.rstrip()


def counted_comments(source: str | bytes) -> list[tuple[int, str]]:
    """Each counted comment line as (line number, normalized text). Bytes honor an encoding cookie."""
    if isinstance(source, bytes):
        tokens = tokenize.tokenize(io.BytesIO(source).readline)
    else:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    found: list[tuple[int, str]] = []
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        line = token.start[0]
        if not is_excluded(line, token.string, token.line):
            found.append((line, _normalize(token.string)))
    return found


def count_source(path: str, source: str | bytes) -> int:
    try:
        return len(counted_comments(source))
    except _READ_ERRORS as error:
        raise RatchetError(f"{path}: the tokenizer cannot read it ({error})") from error


def parse_baseline(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        path, _, count = line.rpartition(" ")
        if not path or not count.isdigit():
            raise RatchetError(
                f"{BASELINE}:{number}: expected `path count`, got {line!r}"
            )
        counts[path] = int(count)
    return counts


def serialize_baseline(counts: Mapping[str, int]) -> str:
    return "".join(
        f"{path} {counts[path]}\n" for path in sorted(counts) if counts[path] > 0
    )


def violations(
    working: Mapping[str, int],
    baseline: Mapping[str, int],
    default_branch: Mapping[str, int],
    tracked: Iterable[str],
) -> list[str]:
    """Every failure message. A path absent from a mapping counts as 0. A path not tracked is outside
    the freeze."""
    tracked_set = set(tracked)
    failures: list[str] = []
    rises = [
        f"{path}: baseline {baseline.get(path, 0)}, now {working[path]}"
        for path in sorted(tracked_set)
        if working.get(path, 0) > baseline.get(path, 0)
    ]
    if rises:
        failures.append("counted comment lines rose in " + "; ".join(rises))
    for path in sorted(baseline):
        if path not in tracked_set:
            failures.append(f"{path}: baseline row is not a tracked .py file")
        elif baseline[path] > default_branch.get(path, 0):
            failures.append(
                f"{path}: baseline {baseline[path]} is above "
                f"{default_branch.get(path, 0)} on the default branch"
            )
    return failures


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)


def tracked_paths(root: Path) -> list[str]:
    result = _git(root, "ls-files", "-z", "*.py")
    if result.returncode != 0:
        raise RatchetError(
            "git ls-files failed: " + result.stderr.decode(errors="replace").strip()
        )
    return sorted(p for p in result.stdout.decode().split("\0") if p)


def working_counts(root: Path, tracked: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    errors: list[str] = []
    for path in tracked:
        file = root / path
        if not file.is_file():
            continue
        try:
            count = count_source(path, file.read_bytes())
        except RatchetError as error:
            errors.append(str(error))
            continue
        if count:
            counts[path] = count
    if errors:
        raise RatchetError("\n".join(errors))
    return counts


def default_ref(root: Path) -> str:
    for ref, name in (
        ("refs/heads/main", "main"),
        ("refs/remotes/origin/main", "origin/main"),
    ):
        if _git(root, "show-ref", "--verify", "--quiet", ref).returncode == 0:
            return name
    raise RatchetError(
        "neither refs/heads/main nor refs/remotes/origin/main exists, so the default branch "
        f"`{DEFAULT_BRANCH}` cannot be read (this check does not fetch)"
    )


def default_counts(root: Path, paths: Iterable[str]) -> dict[str, int]:
    ref = default_ref(root)
    counts: dict[str, int] = {}
    errors: list[str] = []
    for path in paths:
        blob = _git(root, "show", f"{ref}:{path}")
        if blob.returncode != 0:
            continue
        try:
            counts[path] = count_source(path, blob.stdout)
        except RatchetError as error:
            errors.append(str(error))
    if errors:
        raise RatchetError("\n".join(errors))
    return counts


def read_baseline(root: Path) -> dict[str, int]:
    file = root / BASELINE
    return parse_baseline(file.read_text(encoding="utf-8")) if file.exists() else {}


def check(root: Path) -> list[str]:
    """All failures for the tree at `root`, reading git for the tracked set and the default branch."""
    try:
        tracked = tracked_paths(root)
        working = working_counts(root, tracked)
        baseline = read_baseline(root)
        default = default_counts(root, baseline)
    except RatchetError as error:
        return [str(error)]
    return violations(working, baseline, default, tracked)


def update(root: Path) -> int:
    try:
        working = working_counts(root, tracked_paths(root))
        old = read_baseline(root)
    except RatchetError as error:
        print(error, file=sys.stderr)
        return 1
    rises = [
        f"{p}: {old.get(p, 0)} -> {n}"
        for p, n in sorted(working.items())
        if n > old.get(p, 0)
    ]
    if rises:
        print("refusing to raise the baseline: " + "; ".join(rises), file=sys.stderr)
        return 1
    new_text = serialize_baseline(working)
    file = root / BASELINE
    if file.exists() and file.read_bytes() == new_text.encode("utf-8"):
        return 0
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(new_text.encode("utf-8"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m factory.comment_ratchet", description=__doc__
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "update",
        help="write the lower baseline",
        description=(
            "Write the canonical baseline from the current counts. A rise is refused: the "
            "command exits 1 and the baseline file is left untouched. A path that fell to zero "
            "is dropped. Run it from the repo root."
        ),
    )
    parser.parse_args(argv)
    return update(Path.cwd())


if __name__ == "__main__":
    sys.exit(main())
