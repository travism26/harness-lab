"""Behaviour tests for the manifest Auditor, run as a subprocess like a user would."""

import ast
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]
FIXTURES = PROJECT / "fixtures"
SECRET_FIXTURE = FIXTURES / "synthetic" / "secret-shaped.json"
FIXTURE_REL = "projects/manifest-audit/fixtures/synthetic/secret-shaped.json"
FAKE = "sk-ant-" + "FIXTUREONLY"
PEM = "-" * 5 + "BEGIN FIXTURE " + "PRIVATE" + " KEY" + "-" * 5


def run(*args: object, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "manifest_audit", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


def fake_line() -> int:
    lines = SECRET_FIXTURE.read_text(encoding="utf-8").split("\n")
    return next(n for n, line in enumerate(lines, start=1) if FAKE in line)


def secret_row() -> str:
    return f"secret-shaped\t{FIXTURE_REL}\t{fake_line()}\tsecret"


def test_secret_fixture_one_finding() -> None:
    result = run("--root", REPO, SECRET_FIXTURE)
    assert result.returncode == 1
    assert result.stdout.count("\n") == 1
    fields = result.stdout.rstrip("\n").split("\t")
    assert len(fields) == 4
    assert fields[0] == "secret-shaped"
    assert fields[1] == FIXTURE_REL
    assert fields[2].isdigit()
    assert int(fields[2]) == fake_line()
    assert fields[3] == "secret"
    assert FAKE not in result.stdout
    assert FAKE not in result.stderr
    assert result.stderr == ""


def test_benign_fixture_is_clean() -> None:
    result = run("--root", REPO, FIXTURES / "benign" / "tool-weather.json")
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_explicit_directory() -> None:
    result = run("--root", REPO, FIXTURES)
    assert result.returncode == 1
    assert result.stdout == secret_row() + "\n"


def test_partial_prefixes_are_not_findings(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("sk-ant\nBearer SENTINEL-AUTH-1\n", encoding="utf-8")
    result = run("--root", tmp_path, target)
    assert result.returncode == 0
    assert result.stdout == ""


def test_private_key_header_line(tmp_path: Path) -> None:
    target = tmp_path / "key.txt"
    target.write_text(f"one\ntwo\n{PEM}\nfour\n", encoding="utf-8")
    result = run("--root", tmp_path, target)
    assert result.returncode == 1
    assert result.stdout == "secret-shaped\tkey.txt\t3\tsecret\n"
    assert PEM not in result.stdout + result.stderr


def test_one_finding_per_line_and_ordered(tmp_path: Path) -> None:
    same = tmp_path / "same.txt"
    same.write_text(f"{FAKE} and {FAKE}\n", encoding="utf-8")
    result = run("--root", tmp_path, same)
    assert result.stdout == "secret-shaped\tsame.txt\t1\tsecret\n"
    many = tmp_path / "many.txt"
    many.write_text(f"a\n{FAKE}\nb\nc\n{FAKE}\n", encoding="utf-8")
    result = run("--root", tmp_path, many)
    assert (
        result.stdout
        == "secret-shaped\tmany.txt\t2\tsecret\nsecret-shaped\tmany.txt\t5\tsecret\n"
    )


def test_path_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()
    target = other / "x.txt"
    target.write_text(FAKE + "\n", encoding="utf-8")
    result = run("--root", root, target)
    assert result.returncode == 1
    assert result.stdout == f"secret-shaped\t{target.as_posix()}\t1\tsecret\n"


def test_missing_explicit_path(tmp_path: Path) -> None:
    missing = tmp_path / "nope.txt"
    result = run("--root", tmp_path, missing)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() == str(missing)


def test_bad_root(tmp_path: Path) -> None:
    absent = tmp_path / "missing"
    missing = run("--root", absent, SECRET_FIXTURE)
    assert missing.returncode == 2
    assert missing.stdout == ""
    assert missing.stderr.strip() == str(absent)
    a_file = tmp_path / "file.txt"
    a_file.write_text("x", encoding="utf-8")
    result = run("--root", a_file, SECRET_FIXTURE)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() == str(a_file)


def test_unknown_argument() -> None:
    result = run("--nope")
    assert result.returncode == 2
    assert result.stdout == ""


def test_broken_json_fails_without_leaking(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{" + FAKE, encoding="utf-8")
    result = run("--root", tmp_path, broken)
    assert result.returncode == 2
    assert result.stdout == ""
    assert FAKE not in result.stderr
    assert result.stderr.strip() == str(broken)


def test_broken_json_beside_valid_path(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{" + FAKE, encoding="utf-8")
    result = run("--root", REPO, SECRET_FIXTURE, broken)
    assert result.returncode == 2
    assert result.stdout == ""


def test_non_json_file_is_never_a_parse_failure(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text("plain text, not json\n", encoding="utf-8")
    assert run("--root", tmp_path, skill).returncode == 0
    skill.write_text(f"plain text {FAKE}\n", encoding="utf-8")
    assert run("--root", tmp_path, skill).returncode == 1


def test_nul_and_oversize_files_are_skipped(tmp_path: Path) -> None:
    nul = tmp_path / "nul.txt"
    nul.write_bytes(b"\0" + FAKE.encode())
    big = tmp_path / "big.txt"
    big.write_bytes(FAKE.encode() + b"\n" + b"a" * (1_048_576 + 1))
    for target in (nul, big):
        result = run("--root", tmp_path, target)
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr.strip() == target.name
        assert FAKE not in result.stderr


def test_no_paths(tmp_path: Path) -> None:
    result = run("--root", tmp_path)
    assert result.returncode == 0
    assert result.stdout == ""


def test_default_root_is_the_repo() -> None:
    result = run(SECRET_FIXTURE, cwd=PROJECT)
    assert result.returncode == 1
    assert result.stdout == secret_row() + "\n"


def imported_modules(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def compiled_pattern(path: Path, target: str) -> str:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == target for t in node.targets)
            and isinstance(node.value, ast.Call)
        ):
            arg = node.value.args[0]
            assert isinstance(arg, ast.Constant)
            assert isinstance(arg.value, str)
            return arg.value
    raise AssertionError(f"{target} not found in {path}")


def test_source_imports_and_pattern_copy() -> None:
    allowed = {"argparse", "json", "pathlib", "re", "sys", "manifest_audit"}
    for source in (PROJECT / "src" / "manifest_audit").rglob("*.py"):
        assert imported_modules(source) <= allowed, source
    ours = compiled_pattern(PROJECT / "src" / "manifest_audit" / "audit.py", "SECRET")
    theirs = compiled_pattern(REPO / "factory" / "research_note.py", "CREDENTIAL_RE")
    assert ours == theirs


def test_docs() -> None:
    readme = (PROJECT / "README.md").read_text(encoding="utf-8")
    for needle in (
        "secret-shaped",
        "heuristic",
        "a clean scan is not a security guarantee",
    ):
        assert needle in readme
    rules = (PROJECT / "rules.md").read_text(encoding="utf-8")
    assert "secret-shaped" in rules
    assert "factory/research_note.py" in rules
    glossary = (PROJECT / "GLOSSARY.md").read_text(encoding="utf-8")
    for term in ("Auditor", "Finding", "Rule"):
        assert term in glossary
    assert "projects/manifest-audit/GLOSSARY.md" in (
        REPO / "GLOSSARY-MAP.md"
    ).read_text(encoding="utf-8")


def test_check_is_executable() -> None:
    assert os.access(PROJECT / "check", os.X_OK)
