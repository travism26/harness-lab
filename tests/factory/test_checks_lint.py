"""The Lab check and a Project check run for real, for lint: a planted unused import turns each
red. Each check script is copied into a temp folder, so the real tree is never dirtied. A stand-in
`uv` runs ruff and mypy from this environment and skips pytest, so the check does not recurse
into the test suite."""

import os
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UNUSED_IMPORT = "import os\n"
CLEAN = "VALUE = 1\n"

STAND_IN_UV = f"""#!/bin/sh
shift  # run
shift  # --locked
if [ "$1" = "--package" ]; then shift 2; fi
if [ "$1" = "pytest" ]; then exit 0; fi
exec {sys.executable} -m "$@"
"""


def _stand_in_uv(folder: Path) -> dict[str, str]:
    uv = folder / "bin" / "uv"
    uv.parent.mkdir()
    uv.write_text(STAND_IN_UV)
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR)
    return {**os.environ, "PATH": f"{uv.parent}{os.pathsep}{os.environ['PATH']}"}


def _copy_check(source: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "check"
    target.write_text(source.read_text())
    target.chmod(0o755)
    return target


def _run(check: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(check)], env=env, capture_output=True, text=True, check=False
    )


def _lab(folder: Path, module: str) -> Path:
    check = _copy_check(ROOT / "check", folder)
    (folder / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text())
    (folder / "factory").mkdir()
    (folder / "factory" / "planted.py").write_text(module)
    (folder / "tests").mkdir()
    (folder / "tests" / "ok.py").write_text(CLEAN)
    return check


def _project(folder: Path, module: str) -> Path:
    source = ROOT / "projects" / "harness"
    check = _copy_check(source / "check", folder)
    (folder / "pyproject.toml").write_text((source / "pyproject.toml").read_text())
    (folder / "src").mkdir()
    (folder / "src" / "planted.py").write_text(module)
    (folder / "tests").mkdir()
    (folder / "tests" / "ok.py").write_text(CLEAN)
    return check


@pytest.mark.parametrize("build", [_lab, _project], ids=["lab-check", "project-check"])
def test_a_planted_unused_import_turns_a_check_red(
    tmp_path: Path, build: Callable[[Path, str], Path]
) -> None:
    env = _stand_in_uv(tmp_path)
    clean = _run(build(tmp_path / "clean", CLEAN), env)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    planted = _run(build(tmp_path / "planted", UNUSED_IMPORT), env)
    assert planted.returncode != 0
    assert "F401" in planted.stdout
