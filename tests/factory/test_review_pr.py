import json

import pytest

from factory import review_pr
from factory.claude import Result
from factory.review_pr import (
    Findings, Finding, Moves, charge_won, gate_line, label_moves, linked_ticket, parse_findings,
    parse_gate, review_gate,
)


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
    def __init__(self, pr, issue=None, comments=(), ci=None, plant=None):
        self._pr, self._issue = pr, issue
        self.ci = ci
        self.plant = plant
        self.comments, self.added, self.removed = [], [], []
        self.updated = ""
        self._reads = 0
        self._thread, self._next = [], 1
        for body in comments:
            self._thread.append({"id": self._next, "body": body})
            self._next += 1

    def pr(self, repo, number):
        return self._pr

    def issue(self, repo, number):
        return self._issue or {"labels": []}

    def pr_comments(self, repo, number):
        self._reads += 1
        thread = list(self._thread)
        if self.plant and self._reads > 1:
            return [{"id": 0, "body": self.plant}] + thread
        return thread

    def ci_conclusion(self, repo, sha):
        return self.ci

    def comment(self, repo, number, path):
        body = path.read_text()
        self.comments.append(body)
        comment_id = self._next
        self._thread.append({"id": comment_id, "body": body})
        self._next += 1
        return comment_id

    def update_comment(self, repo, comment_id, path):
        body = path.read_text()
        self.updated = body
        for item in self._thread:
            if item["id"] == comment_id:
                item["body"] = body

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


def test_gate_line_round_trips():
    line = gate_line("ba2ea98635fd261912159e8bc8f4f54f1f5411d0", True, "ci", ci_run=99,
                     nonce="abc", add=("rework", "rework:1"))
    mark = parse_gate(line)
    assert mark.charged and mark.source == "ci" and mark.ci_run == 99
    assert mark.nonce == "abc" and mark.add == ("rework", "rework:1")


def test_review_joins_a_head_ci_already_charged():
    sha = "ba2ea98635fd261912159e8bc8f4f54f1f5411d0"
    comment = {"id": 1, "body": gate_line(sha, True, "ci", ci_run=5, nonce="aa",
                                          add=("rework", "rework:1"))}
    moves = review_gate(["rework", "rework:1"], [comment], sha, True, "failure")
    assert moves == Moves("same-round")


def test_spec_pass_leaves_a_ci_failure_to_the_gate():
    moves = review_gate(["rework", "rework:1"], [], "ba2ea98635fd", False, "failure")
    assert moves == Moves("ci-blocked")


def test_charge_won_is_the_earliest_nonce():
    sha = "ba2ea98635fd"
    earlier = {"id": 1, "body": gate_line(sha, True, "review", nonce="aa", add=("rework", "rework:1"))}
    later = {"id": 2, "body": gate_line(sha, True, "ci", ci_run=3, nonce="bb",
                                       add=("rework", "rework:1"))}
    assert charge_won([earlier, later], sha, "aa")
    assert not charge_won([earlier, later], sha, "bb")
    assert charge_won([], sha, "aa")


def test_a_lost_charge_is_rewritten_and_moves_no_labels(tmp_path):
    _write_review(tmp_path)
    plant = gate_line("abc123", True, "ci", ci_run=9, nonce="aa", add=("rework", "rework:1"))
    gh = FakeGitHub(_pr(labels=()), plant=plant)
    review_pr.apply(_args(tmp_path), gh)
    assert gh.added == [] and gh.removed == []
    assert "charged=0" in gh.updated and "already in a rework round" in gh.updated
    assert "Sent to rework:" not in gh.updated


def test_apply_on_a_pass_and_green_ci_clears_in_progress(tmp_path):
    sha = "abc123"
    (tmp_path / "context.json").write_text(json.dumps(
        {"repo": "o/r", "pr": 3, "base_sha": "b", "head_sha": sha, "code_dir": "pr", "ticket": 7}))
    from dataclasses import asdict
    passed = Findings("ok", "ok", [], [])
    (tmp_path / "findings.json").write_text(json.dumps(asdict(passed)))
    gh = FakeGitHub(_pr(labels=(), head=sha, body="Closes #7"),
                    issue={"labels": [{"name": "in-progress"}]}, ci="success")
    review_pr.apply(_args(tmp_path, head_sha=sha), gh)
    assert "in-progress" in gh.removed
    assert any("factory:settled" in comment for comment in gh.comments)
    assert "round" not in gh.added
