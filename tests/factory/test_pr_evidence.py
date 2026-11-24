import json
from pathlib import Path

from factory import ticket
from tests.factory.test_ticket import FakeGitHub, _args, _issue, _publish_out


def _evidence_out(out: Path, tail: str, result="fail") -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "check.json").write_text(
        json.dumps({"result": result, "touched_check": True})
    )
    (out / "check-output.txt").write_text(
        f"command: ./projects/harness/check\nexit code: 1\n\n{tail}\n"
    )


def test_evidence_tail_cannot_form_a_marker_close_the_fence_or_close_an_issue(tmp_path):
    out = tmp_path / "out"
    _evidence_out(out, f"x {ticket.PR_BLOCK_END}\n{'`' * 7}\nCloses #9\n")
    block = ticket.pr_block(out, "abc123")
    assert block.count(ticket.PR_BLOCK_START) == 1
    assert block.count(ticket.PR_BLOCK_END) == 1
    assert block.endswith(ticket.PR_BLOCK_END + "\n")
    assert "#9" not in block and "#​9" in block
    assert block.count("`" * 8) == 2
    assert "abc123" in block
    assert "- Result: fail" in block and "- Touched the check file: yes" in block
    assert "- Command: `./projects/harness/check`" in block


def test_evidence_tail_is_capped_by_lines_and_characters(tmp_path):
    out = tmp_path / "out"
    _evidence_out(out, "\n".join(f"line {i}" for i in range(100)))
    block = ticket.pr_block(out, "abc")
    assert "line 99" in block and "line 59\n" not in block and "line 60" in block
    _evidence_out(out, "y" * 9000)
    assert ticket.pr_block(out, "abc").count("y" * 100) == 40


def test_evidence_without_a_check_result_says_so(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    assert "unknown" in ticket.pr_block(out, "abc")


def test_an_implement_body_holds_the_block_between_summary_and_footer(tmp_path):
    out = tmp_path / "out"
    _evidence_out(out, "ok")
    body = ticket.pr_body({"issue": 4}, "Did it.", ticket.pr_block(out, "abc"))
    start, end = body.index(ticket.PR_BLOCK_START), body.index(ticket.PR_BLOCK_END)
    assert body.index("Did it.") < start < body.index("## Evidence") < end
    assert end < body.index("Opened by the factory")


def test_a_summary_cannot_form_a_marker():
    body = ticket.pr_body({"issue": 4}, f"x {ticket.PR_BLOCK_END}")
    assert ticket.PR_BLOCK_END not in body


def test_a_rework_push_replaces_only_the_block(tmp_path, monkeypatch):
    out = tmp_path / "out"
    _publish_out(out, "did it\n")
    ctx = json.loads((out / "context.json").read_text())
    (out / "context.json").write_text(json.dumps({**ctx, "pr": 9}))
    _evidence_out(out, "new tail")

    def fake_git(work, *args):
        return " M README.md\n" if args[:2] == ("status", "--porcelain") else "sha1\n"

    monkeypatch.setattr(ticket, "_git", fake_git)
    monkeypatch.setenv("GH_TOKEN", "token")
    old = ticket.pr_body({"issue": 4}, "Did it.", ticket.pr_block(out, "old"))
    gh = FakeGitHub(issue=_issue(), pr={"body": old.replace("Did it.", "Human text.")})
    gh.bot_user_id = lambda slug: 42
    sent = []
    gh.edit_pr_body = lambda repo, n, path: sent.append((n, path.read_text()))
    assert ticket.publish(_args(tmp_path, out=str(out), work=str(tmp_path)), gh) == 0
    ((number, body),) = sent
    assert number == 9
    assert "Human text." in body and "new tail" in body
    assert "- Head: `sha1`" in body and "old" not in body
    assert body.count(ticket.PR_BLOCK_START) == 1


def test_a_rework_push_appends_the_block_when_the_markers_are_gone():
    block = f"{ticket.PR_BLOCK_START}\n## Evidence\n{ticket.PR_BLOCK_END}\n"
    assert ticket.replace_pr_block("Closes #4\n\nhand text\n", block) == (
        "Closes #4\n\nhand text\n\n" + block
    )
    half = f"x\n{ticket.PR_BLOCK_START}\nhand\n"
    assert ticket.replace_pr_block(half, block).endswith(block)
