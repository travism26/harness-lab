"""Review's own Door call (#208)."""

import json
import subprocess

import pytest

from factory import review_pr
from factory.claude import Result
from factory.github import PR_BLOCK_END, PR_BLOCK_START

from .test_review_pr import (
    ANSWER,
    FakeGitHub,
    _args,
    _pr,
    _write_review,
    parse_findings,
)

NOT_STATED = "one-way (not stated)"


def _answer_with_door(door="two-way", reason="a revert undoes it"):
    raw = json.loads(ANSWER[ANSWER.find("{") : ANSWER.rfind("}") + 1])
    raw.update({"door": door, "door_reason": reason})
    return json.dumps(raw)


def test_parse_door_reads_a_good_answer():
    text = "```json\n" + _answer_with_door() + "\n```"
    assert review_pr.parse_door(text) == ("two-way", "a revert undoes it")


@pytest.mark.parametrize(
    "text",
    [ANSWER, _answer_with_door("maybe"), _answer_with_door("Two-Way"), "no json", "{"],
)
def test_parse_door_without_a_valid_door_is_not_stated(text):
    assert review_pr.parse_door(text)[0] == NOT_STATED


def test_parse_findings_accepts_an_answer_with_no_door_keys():
    assert parse_findings(ANSWER).spec_summary


def test_prompt_asks_for_the_door(tmp_path):
    ctx = {
        "repo": "o/r",
        "pr": 3,
        "base_sha": "b",
        "head_sha": "abc123",
        "code_dir": "pr",
        "ticket": None,
    }
    prompt = review_pr.build_prompt(ctx, tmp_path)
    assert '"door"' in prompt and '"door_reason"' in prompt


def test_prepare_leaves_the_factory_block_out_of_ticket_md(tmp_path):
    body = f"intro\n{PR_BLOCK_START}\n**Door:** one-way - x\n{PR_BLOCK_END}\noutro"
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=a", "-c", "user.email=a@b"]
        + ["commit", "-q", "--allow-empty", "-m", "x"],
        check=True,
    )
    args = _args(tmp_path, base_sha="HEAD", head_sha="HEAD")
    review_pr.prepare(args, FakeGitHub(_pr(body=body.replace("intro", "intro"))))
    # the PR above has no closing keyword, so the body is the requirement
    text = (tmp_path / "ticket.md").read_text()
    assert "intro" in text and "outro" in text
    assert "Door" not in text and PR_BLOCK_START not in text


def test_strip_pr_block_with_no_end_marker_strips_to_the_end():
    assert review_pr.strip_pr_block(f"a\n{PR_BLOCK_START}\nb\nc") == "a\n"


@pytest.mark.parametrize(
    "body,expected",
    [
        ("**Door:** two-way - fine", "two-way"),
        ("**Door:** one-way - no", "one-way"),
        ("**Door:** one-way (not stated)", "one-way"),
        ("nothing", None),
    ],
)
def test_door_in_body(body, expected):
    assert review_pr.door_in_body(body) == expected


def test_door_in_body_prefers_the_factory_block():
    body = (
        f"**Door:** two-way - mine\n{PR_BLOCK_START}\n"
        f"**Door:** one-way - x\n{PR_BLOCK_END}"
    )
    assert review_pr.door_in_body(body) == "one-way"


def _apply(tmp_path, door, body, labels=()):
    _write_review(tmp_path)
    if door is not None:
        (tmp_path / "door.json").write_text(json.dumps(door))
    gh = FakeGitHub(_pr(labels=list(labels), body=body))
    review_pr.apply(_args(tmp_path), gh)
    return gh


def test_comment_shows_review_door_and_flags_a_disagreement(tmp_path):
    gh = _apply(
        tmp_path, {"door": "two-way", "reason": "revert works"}, "**Door:** one-way - x"
    )
    comment = gh.comments[0]
    assert "Door: two-way. revert works" in comment
    assert "differ" in comment and "one-way" in comment.split("differ", 1)[1]


@pytest.mark.parametrize("body", ["**Door:** two-way - x", "no door here"])
def test_comment_adds_nothing_when_doors_match_or_body_has_none(tmp_path, body):
    gh = _apply(tmp_path, {"door": "two-way", "reason": "r"}, body)
    assert "Door: two-way. r" in gh.comments[0]
    assert "differ" not in gh.comments[0]


def test_missing_door_file_is_not_stated_and_disagrees_with_two_way(tmp_path):
    gh = _apply(tmp_path, None, "**Door:** two-way - x")
    assert f"Door: {NOT_STATED}" in gh.comments[0]
    assert "differ" in gh.comments[0]


def test_the_door_changes_neither_moves_nor_labels(tmp_path):
    results = []
    for door in (
        {"door": "two-way", "reason": "r"},
        {"door": "one-way", "reason": "r"},
        None,
    ):
        d = tmp_path / str(len(results))
        d.mkdir()
        gh = _apply(d, door, "**Door:** one-way - x", ["rework", "rework:1"])
        results.append((gh.added, gh.removed))
    assert results[0] == results[1] == results[2]


def test_review_writes_door_json_beside_findings(tmp_path):
    ctx = {
        "repo": "o/r",
        "pr": 3,
        "base_sha": "b",
        "head_sha": "abc123",
        "code_dir": "pr",
        "ticket": 7,
    }
    (tmp_path / "context.json").write_text(json.dumps(ctx))
    answer = _answer_with_door("one-way", "drops a column")
    review_pr.review(
        _args(tmp_path), run_agent=lambda p, **kw: Result(True, answer, "success", 0.1)
    )
    assert json.loads((tmp_path / "door.json").read_text()) == {
        "door": "one-way",
        "reason": "drops a column",
    }
