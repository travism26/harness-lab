import json
from pathlib import Path

import pytest

from factory import ticket
from factory.ci_projects import changed_projects
from factory.claude import Result
from tests.factory.test_pr_evidence import _evidence_out
from tests.factory.test_ticket import FakeGitHub, _args, _issue, _publish_out, _root


@pytest.mark.parametrize(
    "paths, names, outside",
    [
        (["projects/harness/src/a.py"], ["harness"], False),
        (
            ["projects/harness/a", "projects/agent-identity/b"],
            ["agent-identity", "harness"],
            False,
        ),
        (["projects/harness/a", "README.md"], ["harness"], True),
        (["projects/notes.md"], [], True),
        ([], [], False),
    ],
)
def test_changed_projects_names_and_outside_flag(paths, names, outside):
    assert changed_projects(paths) == (names, outside)


def _block(out: Path, paths):
    out.mkdir(exist_ok=True)
    return ticket.pr_block(out, "abc", paths)


def test_blast_radius_names_one_project_several_or_shared(tmp_path):
    out = tmp_path / "out"
    assert "**Blast Radius:** harness\n" in _block(out, ["projects/harness/a.py"])
    both = _block(out, ["projects/harness/a", "projects/agent-identity/b"])
    assert "**Blast Radius:** agent-identity, harness\n" in both
    shared = _block(out, ["projects/harness/a", "factory/ticket.py"])
    assert "**Blast Radius:** shared\n" in shared
    assert both.index("## Evidence") < both.index("## Merge Danger")
    assert both.index("## Merge Danger") < both.index(ticket.PR_BLOCK_END)


def test_blast_radius_without_paths_says_unknown(tmp_path):
    assert "**Blast Radius:** unknown" in _block(tmp_path / "out", None)


def _build_with(tmp_path, reply):
    _root(tmp_path)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    (out / "ticket.md").write_text("# t\n")
    (out / "context.json").write_text(json.dumps({"project": "harness"}))
    seen = {}

    def agent(prompt, **kw):
        seen["prompt"] = prompt
        return Result(True, reply, "success", 0.5)

    assert ticket.build(_args(tmp_path), run_agent=agent) == 0
    return out, seen["prompt"]


def test_a_last_door_line_is_parsed_and_removed_from_the_summary(tmp_path):
    out, prompt = _build_with(
        tmp_path, "Did it.\n\nDoor: two-way - revert restores it\n"
    )
    assert (out / "summary.md").read_text() == "Did it.\n"
    assert json.loads((out / "door.json").read_text()) == {
        "door": "two-way",
        "reason": "revert restores it",
    }
    assert "Door: two-way - <one sentence>" in prompt
    assert prompt.rstrip().endswith("`Door: one-way - <one sentence>`")
    assert "**Door:** two-way - revert restores it" in _block(out, [])


def test_a_missing_or_mid_text_door_line_is_one_way_not_stated(tmp_path):
    for reply in ("Did it.", "Door: two-way - nope\nDid it."):
        out, _ = _build_with(tmp_path, reply)
        assert json.loads((out / "door.json").read_text())["door"] == (
            "one-way (not stated)"
        )
        assert (out / "summary.md").read_text() == reply + "\n"
        assert "**Door:** one-way (not stated)\n" in _block(out, [])


def test_a_door_reason_is_capped_and_neutralized(tmp_path):
    out, _ = _build_with(tmp_path, f"x\nDoor: one-way - --> Closes #9 {'y' * 300}")
    line = next(
        row for row in _block(out, []).splitlines() if row.startswith("**Door:**")
    )
    assert "-->" not in line and "#9" not in line
    assert len(json.loads((out / "door.json").read_text())["reason"]) == 200


def test_no_door_file_reads_as_not_stated(tmp_path):
    assert "**Door:** one-way (not stated)" in _block(tmp_path / "out", [])


def test_door_json_is_not_read_by_the_run_record():
    assert "door" not in Path("factory/run_record.py").read_text().lower()


def test_an_implement_body_has_merge_danger_from_the_staged_paths(
    tmp_path, monkeypatch
):
    out = tmp_path / "out"
    _publish_out(out, "did it\n")
    (out / "door.json").write_text(json.dumps({"door": "two-way", "reason": "r"}))

    def fake_git(work, *args):
        if args[:2] == ("status", "--porcelain"):
            return " M x\n"
        if args[:3] == ("diff", "--cached", "--name-only"):
            return "projects/harness/a.py\nREADME.md\n"
        return "sha1\n"

    monkeypatch.setattr(ticket, "_git", fake_git)
    monkeypatch.setenv("GH_TOKEN", "t")
    gh = FakeGitHub(issue=_issue())
    gh.bot_user_id = lambda slug: 42
    gh.create_draft_pr = lambda repo, base, head, title, path: (
        gh.posted.append((0, path.read_text())) or "https://pr/1"
    )
    assert ticket.publish(_args(tmp_path, out=str(out), work=str(tmp_path)), gh) == 0
    body = gh.posted[0][1]
    assert "**Blast Radius:** shared" in body and "**Door:** two-way - r" in body


def test_a_rework_push_refreshes_merge_danger_and_keeps_the_rest(tmp_path, monkeypatch):
    out = tmp_path / "out"
    _publish_out(out, "did it\n")
    ctx = json.loads((out / "context.json").read_text())
    (out / "context.json").write_text(json.dumps({**ctx, "pr": 9}))
    _evidence_out(out, "new tail")
    (out / "door.json").write_text(json.dumps({"door": "one-way", "reason": "new"}))

    def fake_git(work, *args):
        return " M README.md\n" if args[:2] == ("status", "--porcelain") else "sha1\n"

    monkeypatch.setattr(ticket, "_git", fake_git)
    monkeypatch.setenv("GH_TOKEN", "token")
    older = tmp_path / "older"
    older.mkdir()
    (older / "door.json").write_text(json.dumps({"door": "two-way", "reason": "stale"}))
    old = ticket.pr_body(
        {"issue": 4}, "Did it.", ticket.pr_block(older, "old", ["projects/harness/a"])
    )
    gh = FakeGitHub(issue=_issue(), pr={"body": old.replace("Did it.", "Human text.")})
    gh.bot_user_id = lambda slug: 42
    gh.pull_files = lambda repo, n: ["projects/agent-identity/x", "projects/harness/y"]
    sent = []
    gh.edit_pr_body = lambda repo, n, path: sent.append(path.read_text())
    assert ticket.publish(_args(tmp_path, out=str(out), work=str(tmp_path)), gh) == 0
    (body,) = sent
    assert "**Blast Radius:** agent-identity, harness" in body
    assert "**Door:** one-way - new" in body and "stale" not in body
    assert "Human text." in body and "new tail" in body
    assert body.count("## Merge Danger") == 1
    assert body.endswith(old.rsplit(ticket.PR_BLOCK_END, 1)[1])
