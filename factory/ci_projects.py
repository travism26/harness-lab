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
from pathlib import Path
from typing import Iterable, List, Optional

SHARED_PREFIXES = ("factory/", ".github/")
SHARED_FILES = ("pyproject.toml", "uv.lock")


def all_projects(root: Path) -> List[str]:
    return sorted(p.parent.name for p in (root / "projects").glob("*/check") if p.is_file())


def projects_to_check(changed: Iterable[str], projects: List[str]) -> List[str]:
    chosen = set()
    for path in changed:
        if path.startswith(SHARED_PREFIXES) or path in SHARED_FILES:
            return sorted(projects)
        parts = path.split("/")
        if len(parts) > 2 and parts[0] == "projects" and parts[1] in projects:
            chosen.add(parts[1])
    return sorted(chosen)


def changed_files(root: Path, base: str) -> List[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", base, "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="sha to diff HEAD against; empty for all")
    parser.add_argument("--root", default=".", help="repo root (default: current directory)")
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
