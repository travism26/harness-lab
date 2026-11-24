"""Choose which Projects' `check` CI runs (.github/workflows/ci.yml).

Usage:
  uv run python -m factory.ci_projects --base <sha>    # Projects changed since <sha>
  uv run python -m factory.ci_projects --base ""       # every Project

Prints a JSON list of Project names, sorted, for the CI job matrix.

A Project is a folder `projects/<name>/` with a `check` file. CI checks:
- each Project with a changed file under `projects/<name>/`;
- every Project when a change touches what they all share: `factory/`, `.github/`, or the root
  `pyproject.toml` and `uv.lock`;
- every Project when there is no base to diff against (an empty or all-zero sha, as on a new
  branch's first push).

A change touching no Project and nothing shared checks no Project; CI then runs only the factory's
own tests.
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

SHARED_PREFIXES = ("factory/", ".github/")
SHARED_FILES = ("pyproject.toml", "uv.lock")


def all_projects(root: Path) -> list[str]:
    return sorted(
        p.parent.name for p in (root / "projects").glob("*/check") if p.is_file()
    )


def changed_projects(paths: Iterable[str]) -> tuple[list[str], bool]:
    """The Project folders the paths fall in (sorted names) and whether any path lies outside
    `projects/<name>/`, so the change reaches the shared code."""
    names: set[str] = set()
    outside = False
    for path in paths:
        parts = path.split("/")
        if len(parts) > 2 and parts[0] == "projects":
            names.add(parts[1])
        else:
            outside = True
    return sorted(names), outside


def projects_to_check(changed: Iterable[str], projects: list[str]) -> list[str]:
    changed = list(changed)
    if any(p.startswith(SHARED_PREFIXES) or p in SHARED_FILES for p in changed):
        return sorted(projects)
    names, _ = changed_projects(changed)
    return [name for name in names if name in projects]


def changed_files(root: Path, base: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", base, "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base", required=True, help="sha to diff HEAD against; empty for all"
    )
    parser.add_argument(
        "--root", default=".", help="repo root (default: current directory)"
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    projects = all_projects(root)
    if args.base.strip("0") == "":
        chosen = projects
    else:
        chosen = projects_to_check(changed_files(root, args.base), projects)
    print(json.dumps(chosen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
