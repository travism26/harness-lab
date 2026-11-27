"""The comment ratchet: the counter, the violation rules, the update command, and the real tree."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from factory import comment_ratchet as ratchet

ROOT = Path(__file__).resolve().parents[2]

COUNT_CASES: dict[str, tuple[str, int]] = {
    "code only": ("x = 1\n", 0),
    "hash in a string": ("x = '# not a comment'\n", 0),
    "docstring": ('"""# one\n# two\n"""\n', 0),
    "inline": ("x = 1  # why\n", 1),
    "inline reworded": ("x = 1  # a different why\n", 1),
    "block": ("# a\n# b\n# c\nx = 1\n", 3),
    "shebang on line 1": ("#!/usr/bin/env python\nx = 1\n", 0),
    "shebang below line 1": ("x = 1\n#!/usr/bin/env python\n", 1),
    "cookie on line 1": ("# -*- coding: utf-8 -*-\nx = 1\n", 0),
    "cookie on line 2": ("#!/usr/bin/python\n# coding=latin-1\nx = 1\n", 0),
    "cookie on line 3": ("x = 1\ny = 2\n# coding: utf-8\n", 1),
    "noqa": ("import os  # noqa\n", 0),
    "noqa one code": ("import os  # noqa: E402\n", 0),
    "noqa two codes": ("import os  # noqa: E402, F401\n", 0),
    "type ignore": ("x = 1  # type: ignore\n", 0),
    "type ignore code": ("x = 1  # type: ignore[attr-defined]\n", 0),
    "pragma two words": ("if x:  # pragma: no cover\n    pass\n", 0),
    "pragma one word": ("if x:  # pragma: nocover\n    pass\n", 0),
    "directive plus prose": ("import os  # noqa: E402 because of the path\n", 1),
    "type lookalike": ("x = 1  # type: int\n", 1),
    "upper noqa": ("import os  # NOQA\n", 1),
    "fmt off": ("# fmt: off\nx = 1\n", 1),
    "commented-out code": ("# x = compute(1)\n", 1),
}


@pytest.mark.parametrize(
    ("source", "expected"), COUNT_CASES.values(), ids=COUNT_CASES.keys()
)
def test_counts(source: str, expected: int) -> None:
    assert len(ratchet.counted_comments(source)) == expected
    assert len(ratchet.counted_comments(source.encode())) == expected


def test_counted_comment_reports_line_and_normalized_text() -> None:
    assert ratchet.counted_comments("x = 1\ny = 2  #  spaced   \n#bare\n") == [
        (2, " spaced"),
        (3, "bare"),
    ]


def test_cookie_is_honored_when_reading_bytes() -> None:
    source = "# coding: latin-1\n# caf\xe9\n".encode("latin-1")
    assert ratchet.counted_comments(source) == [(2, "caf\xe9")]


VIOLATION_CASES: dict[str, dict[str, object]] = {
    "rise names every path": {
        "working": {"a.py": 3, "b.py": 2, "c.py": 1},
        "baseline": {"a.py": 2, "b.py": 1, "c.py": 1},
        "default": {"a.py": 2, "b.py": 1, "c.py": 1},
        "tracked": ["a.py", "b.py", "c.py"],
        "expect": ["a.py: baseline 2, now 3", "b.py: baseline 1, now 2"],
        "count": 1,
    },
    "raised baseline caught by default branch": {
        "working": {"a.py": 3},
        "baseline": {"a.py": 3},
        "default": {"a.py": 2},
        "tracked": ["a.py"],
        "expect": ["a.py: baseline 3 is above 2 on the default branch"],
        "count": 1,
    },
    "under the ceiling passes": {
        "working": {"a.py": 1},
        "baseline": {"a.py": 2},
        "default": {"a.py": 2},
        "tracked": ["a.py"],
        "expect": [],
        "count": 0,
    },
    "tracked path without a row": {
        "working": {"new.py": 1},
        "baseline": {},
        "default": {},
        "tracked": ["new.py"],
        "expect": ["new.py: baseline 0, now 1"],
        "count": 1,
    },
    "baseline row not tracked": {
        "working": {},
        "baseline": {"gone.py": 1},
        "default": {"gone.py": 1},
        "tracked": [],
        "expect": ["gone.py: baseline row is not a tracked .py file"],
        "count": 1,
    },
    "untracked path is outside the freeze": {
        "working": {"scratch.py": 9},
        "baseline": {},
        "default": {},
        "tracked": ["a.py"],
        "expect": [],
        "count": 0,
    },
    "rename starts at zero": {
        "working": {"new.py": 2},
        "baseline": {"old.py": 2},
        "default": {"old.py": 2},
        "tracked": ["new.py"],
        "expect": [
            "new.py: baseline 0, now 2",
            "old.py: baseline row is not a tracked .py file",
        ],
        "count": 2,
    },
}


@pytest.mark.parametrize("case", VIOLATION_CASES.values(), ids=VIOLATION_CASES.keys())
def test_violations(case: dict[str, object]) -> None:
    failures = ratchet.violations(
        case["working"],  # type: ignore[arg-type]
        case["baseline"],  # type: ignore[arg-type]
        case["default"],  # type: ignore[arg-type]
        case["tracked"],  # type: ignore[arg-type]
    )
    assert len(failures) == case["count"]
    text = "\n".join(failures)
    for fragment in case["expect"]:  # type: ignore[attr-defined]
        assert fragment in text


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path, files: dict[str, str | bytes], baseline: str | None) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
    if baseline is not None:
        (tmp_path / ratchet.BASELINE).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / ratchet.BASELINE).write_text(baseline)
    _git(tmp_path, "add", ".")
    return tmp_path


def _run_update(repo: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "factory.comment_ratchet", "update"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_update_writes_lower_baseline_and_drops_zero(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"a.py": "# one\n", "b.py": "x = 1\n"}, "a.py 3\nb.py 2\n")
    assert _run_update(repo).returncode == 0
    assert (repo / ratchet.BASELINE).read_text() == "a.py 1\n"


def test_update_on_canonical_file_exits_zero_and_leaves_it(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"a.py": "# one\n"}, "a.py 1\n")
    before = (repo / ratchet.BASELINE).stat().st_mtime_ns
    assert _run_update(repo).returncode == 0
    assert (repo / ratchet.BASELINE).read_bytes() == b"a.py 1\n"
    assert (repo / ratchet.BASELINE).stat().st_mtime_ns == before


def test_update_refuses_a_rise(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path, {"a.py": "# one\n", "b.py": "# x\n# y\n"}, "a.py 3\nb.py 1\n"
    )
    result = _run_update(repo)
    assert result.returncode == 1
    assert "b.py" in result.stderr
    assert (repo / ratchet.BASELINE).read_bytes() == b"a.py 3\nb.py 1\n"


def test_update_help_says_rise_refused_and_file_untouched() -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "factory.comment_ratchet", "update", "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    flat = " ".join(result.stdout.split())
    assert "rise is refused" in flat
    assert "baseline file is left untouched" in flat


def test_check_fails_a_file_the_tokenizer_cannot_read(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"bad.py": b'x = """never closed\n'}, "")
    _git(repo, "commit", "-q", "-m", "init")
    failures = ratchet.check(repo)
    assert any("bad.py" in failure for failure in failures)


def test_check_fails_without_a_default_branch_ref(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"a.py": "x = 1\n"}, "")
    failures = ratchet.check(repo)
    assert failures
    assert "main" in failures[0]


def test_check_passes_a_repo_matching_main(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"a.py": "# one\n"}, "a.py 1\n")
    _git(repo, "commit", "-q", "-m", "init")
    assert ratchet.check(repo) == []


def test_tree_matches_baseline_and_default_branch() -> None:
    tracked = ratchet.tracked_paths(ROOT)
    working = ratchet.working_counts(ROOT, tracked)
    baseline_bytes = (ROOT / ratchet.BASELINE).read_bytes()
    baseline = ratchet.parse_baseline(baseline_bytes.decode("utf-8"))
    default = ratchet.default_counts(ROOT, baseline)
    assert {p: n for p, n in working.items() if n > baseline.get(p, 0)} == {}
    assert baseline_bytes == ratchet.serialize_baseline(baseline).encode("utf-8")
    assert {p: n for p, n in baseline.items() if n > default.get(p, 0)} == {}
    assert ratchet.check(ROOT) == []


AUDIT_ACTIONS = {
    "Tautology": "delete later",
    "Excuse": "fix later",
    "Stale": "delete later",
    "Decision Record": "keep",
}
AUDIT_HEADER_SENTENCES = (
    "This file is not a Retro and not a Research note.",
    "The line restates the code a reader can already see.",
    (
        "A repo-root path that CODING_STANDARDS.md requires is not a Tautology when the path is "
        "the point of the line."
    ),
    (
        "The line names a behavior, date, label, file, or constraint the current code and docs "
        "do not match."
    ),
    "When two categories could fit and the line is false now, it is Stale.",
    (
        "The line apologises for a hack, a workaround, a copy, or a special case, and the code "
        "could be changed so the line would go."
    ),
    "The line records a choice a reader would otherwise redo or undo.",
    "A pointer at an ADR or a repo-root path can be this.",
)


def _audit_parts() -> tuple[str, list[list[str]]]:
    text = (ROOT / "docs" / "python-comment-audit.md").read_text(encoding="utf-8")
    parts = re.split(
        r"^```comment-audit\n(.*?)^```\n", text, flags=re.MULTILINE | re.DOTALL
    )
    assert len(parts) == 3, "expected exactly one comment-audit fence"
    rows = [row.split("\t", 3) for row in parts[1].split("\n") if row]
    bad = [row for row in rows if len(row) != 4]
    assert not bad, f"a row does not have four tab-separated fields: {bad[0]!r}"
    return parts[0], rows


def test_the_audit_lists_every_counted_comment_once() -> None:
    """The audit fence matches the counted comments one for one, with a valid category and action."""
    header, rows = _audit_parts()
    expected = [
        (path, text)
        for path in ratchet.tracked_paths(ROOT)
        for _, text in ratchet.counted_comments((ROOT / path).read_bytes())
    ]
    listed = [(row[0], row[3]) for row in rows]
    first = next(
        (i for i, pair in enumerate(zip(listed, expected)) if pair[0] != pair[1]),
        min(len(listed), len(expected)),
    )
    assert listed == expected, (
        f"the audit has {len(listed)} rows, the tree {len(expected)}; first difference at row "
        f"{first + 1}: audit {listed[first : first + 1]}, tree {expected[first : first + 1]}"
    )
    for path, category, action, text in rows:
        assert category in AUDIT_ACTIONS, (
            f"{path}: unknown category {category!r} for {text!r}"
        )
        assert action == AUDIT_ACTIONS[category], (
            f"{path}: {category} carries {AUDIT_ACTIONS[category]!r}, not {action!r}, for {text!r}"
        )
    flat = " ".join(header.replace("`", "").split())
    for sentence in AUDIT_HEADER_SENTENCES:
        assert sentence in flat, f"the audit header lacks: {sentence}"
