import argparse
import json

import pytest

from factory import ticket
from factory.claude import Result
from factory.review_pr import MARKER

REPO = "travism26/harness-lab"


class FakeGitHub:
    def __init__(self, issue=None, pr=None, in_progress=(), comments=()):
        self._issue, self._pr = issue, pr
        self._in_progress, self._comments = list(in_progress), list(comments)
        self.posted, self.added, self.removed = [], [], []

    def issue(self, repo, number):
        return self._issue

    def pr(self, repo, number):
        return self._pr

    def open_issues_labelled(self, repo, label):
        return self._in_progress

    def pr_comments(self, repo, number):
        return self._comments

    def comment(self, repo, number, path):
        self.posted.append((number, path.read_text()))

    def add_labels(self, repo, number, labels):
        self.added += list(labels)

    def remove_labels(self, repo, number, labels):
        self.removed += list(labels)


def _issue(author="travism26", state="OPEN", labels=("ready-for-agent", "project:harness")):
    return {"title": "Add a loop", "body": "Acceptance: it loops", "state": state,
            "author": {"login": author}, "labels": [{"name": n} for n in labels]}


def _root(tmp_path, name="harness", executable=True):
    check = tmp_path / "root" / "projects" / name / "check"
    check.parent.mkdir(parents=True, exist_ok=True)
    check.write_text("#!/usr/bin/env bash\n")
    check.chmod(0o755 if executable else 0o644)


def _args(tmp_path, **kw):
    base = dict(root=str(tmp_path / "root"), repo=REPO, issue=4, pr=9, out=str(tmp_path / "out"), login="subscription",
                app_slug="harness-factory", run_url="https://run", work=str(tmp_path),
                model="sonnet", max_budget_usd=5.0)
    base.update(kw)
    return argparse.Namespace(**base)


def test_claim_labels_the_ticket_and_writes_it(tmp_path):
    _root(tmp_path)
    gh = FakeGitHub(issue=_issue())
    assert ticket.claim(_args(tmp_path), gh) == 0
    assert gh.removed == ["ready-for-agent"] and gh.added == ["in-progress"]
    ctx = json.loads((tmp_path / "out" / "context.json").read_text())
    assert ctx["branch"] == "factory/issue-4" and ctx["pr"] is None
    assert ctx["project"] == "harness"
    prompt = ticket.build_prompt(tmp_path / "out")
    assert "projects/harness/check" in prompt and "projects/harness/GLOSSARY.md" in prompt
    assert "it loops" in (tmp_path / "out" / "ticket.md").read_text()


@pytest.mark.parametrize("labels, executable, match", [
    (("ready-for-agent",), True, "no `project:<name>` label"),
    (("ready-for-agent", "project:harness", "project:other"), True, "more than one"),
    (("ready-for-agent", "project:missing"), True, "no executable `projects/missing/check`"),
    (("ready-for-agent", "project:harness"), False, "no executable `projects/harness/check`"),
])
def test_claim_refuses_a_ticket_without_a_buildable_project(tmp_path, labels, executable, match):
    _root(tmp_path, executable=executable)
    args = _args(tmp_path)
    gh = FakeGitHub(issue=_issue(labels=labels))
    with pytest.raises(ticket.Refused, match=match):
        ticket.claim(args, gh)
    assert gh.added == [] and gh.removed == ["ready-for-agent"]
    assert "did not start" in gh.posted[0][1] and not (tmp_path / "out" / "context.json").exists()


@pytest.mark.parametrize("labels, executable, match", [
    ((), True, "no `project:<name>` label"),
    (("project:harness", "project:other"), True, "more than one"),
    (("project:missing",), True, "no executable `projects/missing/check`"),
    (("project:harness",), False, "no executable `projects/harness/check`"),
])
def test_revise_refuses_a_ticket_without_a_buildable_project(tmp_path, labels, executable, match):
    _root(tmp_path, executable=executable)
    gh = FakeGitHub(issue=_issue(labels=labels), pr=_pr(), comments=[{"body": MARKER}])
    with pytest.raises(RuntimeError, match=match):
        ticket.revise(_args(tmp_path), gh)
    assert "did not start a rework round" in gh.posted[0][1]
    assert not (tmp_path / "out" / "review.md").exists()


def test_claim_refuses_a_second_ticket_in_progress(tmp_path):
    _root(tmp_path)
    gh = FakeGitHub(issue=_issue(), in_progress=[2, 4])
    with pytest.raises(ticket.Refused, match="one Ticket at a time: #2"):
        ticket.claim(_args(tmp_path), gh)
    assert gh.added == [] and gh.removed == ["ready-for-agent"]
    assert "did not start" in gh.posted[0][1]


def test_claim_refuses_someone_elses_ticket_on_the_subscription(tmp_path):
    _root(tmp_path)
    gh = FakeGitHub(issue=_issue(author="stranger"))
    with pytest.raises(ticket.Refused, match="switch rule"):
        ticket.claim(_args(tmp_path), gh)


def test_claim_allows_someone_elses_ticket_on_openrouter(tmp_path):
    _root(tmp_path)
    gh = FakeGitHub(issue=_issue(author="stranger"))
    assert ticket.claim(_args(tmp_path, login="openrouter"), gh) == 0


def _pr(labels=("rework", "rework:1"), branch="factory/issue-4"):
    return {"state": "OPEN", "body": "Closes #4", "headRefName": branch,
            "author": {"login": "harness-factory[bot]"},
            "labels": [{"name": n} for n in labels]}


def test_revise_takes_the_latest_factory_review(tmp_path):
    _root(tmp_path)
    comments = [{"body": f"{MARKER}\nold"}, {"body": "human chat"}, {"body": f"{MARKER}\nnew"}]
    gh = FakeGitHub(issue=_issue(), pr=_pr(), comments=comments)
    assert ticket.revise(_args(tmp_path), gh) == 0
    out = tmp_path / "out"
    assert (out / "review.md").read_text().endswith("new")
    assert json.loads((out / "context.json").read_text())["pr"] == 9
    assert "rework round" in ticket.build_prompt(out)


@pytest.mark.parametrize("pr", [_pr(labels=("rework", "ready-for-human")), _pr(labels=()),
                                _pr(branch="fm/hand-made")])
def test_revise_refuses_prs_not_waiting_for_factory_rework(tmp_path, pr):
    _root(tmp_path)
    gh = FakeGitHub(issue=_issue(), pr=pr, comments=[{"body": MARKER}])
    with pytest.raises(RuntimeError):
        ticket.revise(_args(tmp_path), gh)


def test_build_runs_the_agent_in_the_work_checkout(tmp_path):
    _root(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "ticket.md").write_text("# t\n")
    (out / "context.json").write_text(json.dumps({"project": "harness"}))
    seen = {}

    def agent(prompt, **kw):
        seen.update(kw, prompt=prompt)
        return Result(True, "Added the loop.", "success", 0.5)

    assert ticket.build(_args(tmp_path), run_agent=agent) == 0
    assert seen["may_edit"] and "WebFetch" in seen["disallowed_tools"]
    assert seen["cwd"] == str(tmp_path.resolve())
    assert "rework round" not in seen["prompt"]
    assert "`CLAUDE.md`, `GLOSSARY-MAP.md`" in seen["prompt"]
    assert "`docs/design.md`" not in seen["prompt"]
    assert "`projects/harness/check`" in seen["prompt"]
    assert "`projects/harness/`" in seen["prompt"]
    assert "projects/harness/GLOSSARY.md" in seen["prompt"]
    assert "projects/harness/docs/adr/" in seen["prompt"]
    assert "uv run pytest" not in seen["prompt"]
    assert (out / "summary.md").read_text() == "Added the loop.\n"


def test_pr_body_closes_the_ticket():
    assert ticket.pr_body({"issue": 4}, "Did it.").startswith("Closes #4\n")


def test_release_drops_in_progress(tmp_path):
    gh = FakeGitHub(issue=_issue(labels=("in-progress",)))
    ticket.release(_args(tmp_path), gh)
    assert gh.removed == ["in-progress"] and "failed" in gh.posted[0][1]
