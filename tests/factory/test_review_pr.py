import json

import pytest

from factory import review_pr
from factory.claude import Result
from factory.review_pr import Findings, Finding, Moves, label_moves, linked_ticket, parse_findings


@pytest.mark.parametrize("labels,blocker,expected", [
    ([], True, Moves("rework", add=("rework", "rework:1"))),
    (["rework", "rework:1"], True, Moves("rework", add=("rework", "rework:2"),
                                         remove=("rework:1", "rework"))),
    (["rework", "rework:2"], True, Moves("human", add=("ready-for-human",), remove=("rework",))),
    (["rework", "rework:2"], False, Moves("pass", remove=("rework",))),
    (["rework:1"], False, Moves("pass")),
    (["ready-for-human", "rework:2"], True, Moves("human-owned")),
])
def test_two_rework_rounds_then_a_human(labels, blocker, expected):
    assert label_moves(labels, blocker) == expected


def test_linked_ticket_reads_closing_keywords_for_this_repo_only():
    assert linked_ticket("Closes #12", "o/r") == 12
    assert linked_ticket("fixes other/repo#3 and resolves #4", "o/r") == 4
    assert linked_ticket("mentions #5", "o/r") is None


ANSWER = """Here you go:
```json
{"spec_summary": "Missing a test.", "standards_summary": "Fine.",
 "spec_findings": [{"kind": "missing_requirement", "description": "no test",
   "resolution": "add one", "file_path": null}],
 "standards_findings": [{"kind": "baseline_smell", "description": "name",
   "resolution": "rename", "file_path": "a.py:1"}]}
```"""


def test_parse_findings_from_fenced_json():
    findings = parse_findings(ANSWER)
    assert findings.blocker
    assert findings.standards_findings[0].file_path == "a.py:1"


def test_only_spec_requirement_findings_block():
    f = Findings("s", "t", [Finding("scope_creep", "d", "r")], [Finding("repo_standard", "d", "r")])
    assert not f.blocker


@pytest.mark.parametrize("text", ["no json", '{"spec_summary": "x"}',
                                  '{"spec_summary": "", "standards_summary": "",'
                                  ' "spec_findings": [{"kind": "nitpick"}]}'])
def test_parse_findings_rejects_bad_answers(text):
    with pytest.raises((ValueError, KeyError)):
        parse_findings(text)


class FakeGitHub:
    def __init__(self, pr, issue=None):
        self._pr, self._issue = pr, issue
        self.comments, self.added, self.removed = [], [], []

    def pr(self, repo, number):
        return self._pr

    def issue(self, repo, number):
        return self._issue

    def comment(self, repo, number, path):
        self.comments.append(path.read_text())

    def add_labels(self, repo, number, labels):
        self.added += list(labels)

    def remove_labels(self, repo, number, labels):
        self.removed += list(labels)


def _pr(labels=(), head="abc123", author="harness-factory[bot]", body="Closes #7"):
    return {"state": "OPEN", "title": "t", "body": body, "headRefOid": head,
            "author": {"login": author}, "labels": [{"name": n} for n in labels]}


def _args(tmp_path, **kw):
    import argparse
    base = dict(repo="travism26/harness-lab", pr=3, out=str(tmp_path), base_sha="b",
                head_sha="abc123", code_dir=str(tmp_path), login="subscription",
                app_slug="harness-factory", model="sonnet", max_budget_usd=1.0)
    base.update(kw)
    return argparse.Namespace(**base)


def test_prepare_refuses_the_subscription_for_someone_elses_ticket(tmp_path):
    gh = FakeGitHub(_pr(), issue={"title": "x", "body": "y", "author": {"login": "stranger"}})
    with pytest.raises(RuntimeError, match="switch rule"):
        review_pr.prepare(_args(tmp_path), gh)


def test_review_writes_findings_from_the_agent(tmp_path):
    (tmp_path / "context.json").write_text(json.dumps(
        {"repo": "o/r", "pr": 3, "base_sha": "b", "head_sha": "abc123", "code_dir": "pr",
         "ticket": 7}))
    seen = {}

    def agent(prompt, **kw):
        seen.update(kw, prompt=prompt)
        return Result(True, ANSWER, "success", 0.1)

    assert review_pr.review(_args(tmp_path), run_agent=agent) == 0
    assert "Bash" in seen["disallowed_tools"] and seen["allowed_tools"] == ["Read", "Grep", "Glob"]
    assert "`GLOSSARY-MAP.md`" in seen["prompt"]
    assert "`docs/design.md`" not in seen["prompt"]
    assert json.loads((tmp_path / "findings.json").read_text())["spec_findings"]


def test_review_fails_loudly_at_the_budget_cap(tmp_path):
    (tmp_path / "context.json").write_text(json.dumps(
        {"repo": "o/r", "pr": 3, "base_sha": "b", "head_sha": "h", "code_dir": "pr", "ticket": None}))
    agent = lambda prompt, **kw: Result(False, "", "error_max_budget_usd", 1.04)  # noqa: E731
    with pytest.raises(RuntimeError, match="budget cap"):
        review_pr.review(_args(tmp_path), run_agent=agent)


def _write_review(tmp_path, head="abc123"):
    (tmp_path / "context.json").write_text(json.dumps(
        {"repo": "o/r", "pr": 3, "base_sha": "b", "head_sha": head, "code_dir": "pr", "ticket": 7}))
    from dataclasses import asdict
    (tmp_path / "findings.json").write_text(json.dumps(asdict(parse_findings(ANSWER))))


def test_apply_posts_and_sends_to_rework(tmp_path):
    _write_review(tmp_path)
    gh = FakeGitHub(_pr(labels=["rework", "rework:1"]))
    review_pr.apply(_args(tmp_path), gh)
    assert gh.removed == ["rework:1", "rework"] and gh.added == ["rework", "rework:2"]
    assert "round 2 of 2" in gh.comments[0]


def test_apply_on_a_moved_head_changes_no_labels(tmp_path):
    _write_review(tmp_path, head="old")
    gh = FakeGitHub(_pr(head="new"))
    review_pr.apply(_args(tmp_path), gh)
    assert gh.added == [] and gh.removed == [] and "moved on" in gh.comments[0]
