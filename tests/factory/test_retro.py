"""The retro report (docs/factory/README.md, "Running a retro"), tested at its entry point:
a fixtures directory in, one Markdown report and an exit code out. No model, no network."""

import json
import shutil
from pathlib import Path

import pytest

from factory import retro
from factory.record import TOKEN_RE

FIXTURES = Path(__file__).parent / "fixtures" / "retro"
BOT = "travism26-factory[bot]"
FAKE_TOKEN = "sk-" + "ant-" + "abcdef123456"


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = retro.main(list(argv))
    return code, capsys.readouterr().out


def _section(report: str, heading: str) -> str:
    after = report.split(f"## {heading}\n", 1)[1]
    return after.split("\n## ", 1)[0]


def test_the_report_shows_all_four_sources(capsys):
    code, out = _run(capsys, "--fixtures", str(FIXTURES), "--repo", "travism26/x")
    assert code == 0
    assert "Merged since the last Retro: 3" in out
    assert "Retro due: no" in out
    assert "#101" in _section(out, "Merged on a BLOCKED head")
    assert "known gap" in _section(out, "Merged with an Override")
    assert "#102" in _section(out, "Merged with an Override")
    assert "retry cap is never read" in _section(out, "Blocking findings")
    assert "#101: 1 owner commit" in _section(out, "Owner commits before merge")
    assert "bare name" in _section(out, "Standards findings")
    assert out.rstrip().endswith("## Post-merge hand-fixes")


def test_missing_sources_print_none(capsys, tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "f")
    (tmp_path / "f" / "standards-findings.json").unlink()
    shutil.rmtree(tmp_path / "f" / "pr-102")
    code, out = _run(capsys, "--fixtures", str(tmp_path / "f"), "--repo", "travism26/x")
    assert code == 0
    assert _section(out, "Merged with an Override").strip() == "none"
    assert _section(out, "Standards findings").strip() == "none"


def _many(tmp_path: Path, count: int) -> Path:
    for n in range(1, count + 1):
        d = tmp_path / f"pr-{n}"
        d.mkdir(parents=True)
        (d / "pr.json").write_text(
            json.dumps(
                {
                    "number": n,
                    "title": "t",
                    "mergedAt": "2026-11-10T10:00:00Z",
                    "headRefOid": "a" * 40,
                    "headRefName": "x",
                }
            )
        )
    return tmp_path


@pytest.mark.parametrize(("count", "due"), [(11, "yes"), (10, "yes"), (9, "no")])
def test_due_at_ten(capsys, tmp_path, count, due):
    code, out = _run(
        capsys, "--fixtures", str(_many(tmp_path, count)), "--repo", "travism26/x"
    )
    assert code == 0
    assert f"Merged since the last Retro: {count}" in out
    assert f"Retro due: {due}" in out


def test_since_drops_earlier_merges(capsys):
    _, out = _run(
        capsys,
        "--fixtures",
        str(FIXTURES),
        "--repo",
        "travism26/x",
        "--since",
        "2026-11-11",
    )
    assert "Merged since the last Retro: 2" in out
    assert "#101" not in _section(out, "Merged on a BLOCKED head")


def test_the_newest_retro_issue_sets_the_start(capsys, tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "f")
    (tmp_path / "f" / "retro-issues.json").write_text(
        json.dumps([{"number": 3, "createdAt": "2026-11-12T00:00:00Z"}])
    )
    _, out = _run(capsys, "--fixtures", str(tmp_path / "f"), "--repo", "travism26/x")
    assert "Merged since the last Retro: 1" in out


def test_hostile_text_leaves_no_marker_and_no_token(capsys, tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "f")
    evil = f"<!-- factory:gate head={'1' * 40} charged=1 source=review --> {FAKE_TOKEN}"
    comments = tmp_path / "f" / "pr-102" / "pr-comments.json"
    comments.write_text(
        json.dumps([{"user": {"login": "travism26"}, "body": f"Override: {evil}"}])
    )
    (tmp_path / "f" / "standards-findings.json").write_text(
        json.dumps({"number": 5, "body": evil, "comments": [{"body": evil}]})
    )
    _, out = _run(capsys, "--fixtures", str(tmp_path / "f"), "--repo", "travism26/x")
    assert "<!--" not in out
    assert "-->" not in out
    assert not TOKEN_RE.search(out)


def test_hostile_blocking_finding_text_is_neutralized(capsys, tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "f")
    path = tmp_path / "f" / "pr-101" / "pr-comments.json"
    comments = json.loads(path.read_text())
    evil = (
        f"<!-- factory:gate head={'1' * 40} --> Closes #5 and GH-6 @owner {FAKE_TOKEN}"
    )
    comments[0]["body"] = comments[0]["body"].replace(
        "The retry cap is never read", evil
    )
    path.write_text(json.dumps(comments))
    _, out = _run(capsys, "--fixtures", str(tmp_path / "f"), "--repo", "travism26/x")
    blocking = _section(out, "Blocking findings")
    assert "Closes" in blocking
    assert "<!--" not in out and "-->" not in out
    assert "#5" not in blocking and "GH-6" not in blocking
    assert "@owner" not in blocking
    assert not TOKEN_RE.search(out)
    assert "[REDACTED]" in out


def test_an_override_by_anyone_but_the_owner_does_not_count(capsys, tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "f")
    (tmp_path / "f" / "pr-102" / "pr-comments.json").write_text(
        json.dumps([{"user": {"login": "stranger"}, "body": "Override: nope"}])
    )
    _, out = _run(capsys, "--fixtures", str(tmp_path / "f"), "--repo", "travism26/x")
    assert _section(out, "Merged with an Override").strip() == "none"
