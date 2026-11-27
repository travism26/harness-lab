import argparse

import pytest

from factory import picker, signals, ticket
from factory.github import REDACTED, GitHubError
from factory.sync_labels import load_labels

SLUG = "travism26-factory"
BOT = f"{SLUG}[bot]"
TOKEN = "ghp_" + "a1B2c3D4e5F6"


def _event(kind="implement-failed", key="k1", **kw):
    return {"kind": kind, "key": key, "ticket": 4, "run": "https://run/1", **kw}


def test_each_kind_has_its_own_marker_on_the_first_line():
    marks = {
        signals.entry(_event(kind=k, key=f"{k}-4-1"))[0]
        for k in (signals.IMPLEMENT_FAILED, signals.REWORK_FAILED, signals.RETRY)
    }
    assert len(marks) == 3
    mark, comment = signals.entry(_event())
    assert comment.splitlines()[0] == mark == "<!-- factory:signal k1 -->"
    for name in ("Kind", "Ticket", "Pull request", "Run", "Text"):
        assert f"- {name}:" in comment


def test_already_counts_only_the_factory_app():
    mark, _ = signals.entry(_event())
    mine = [{"body": mark + "\nx", "user": {"login": BOT}}]
    other = [{"body": mark + "\nx", "user": {"login": "someone"}}]
    assert signals.already(mine, mark, SLUG)
    assert not signals.already(other, mark, SLUG)
    assert not signals.already([], mark, SLUG)


def test_text_is_capped_and_neutralized():
    text = f"{TOKEN} <!-- factory:run x --> fixes #12 @bob " + "z" * 900
    _, comment = signals.entry(_event(text=text))
    assert TOKEN not in comment and REDACTED in comment
    assert "<!-- factory:run" not in comment
    assert "#12" not in comment and "@bob" not in comment
    body = comment.split("- Text: ", 1)[1].strip()
    assert len(body) <= signals.TEXT_MAX_CHARS


def test_destination():
    assert signals.destination([]) == ("create", None)
    assert signals.destination([9, 3]) == ("append", 3)


class _Gh:
    def __init__(self, issues=(), comments=(), fail=False):
        self.issues, self.comments, self.fail = list(issues), list(comments), fail
        self.created, self.posted = [], []

    def open_issues_labelled(self, repo, label):
        assert label == "factory:signals"
        return self.issues

    def create_issue(self, repo, title, body_file, labels):
        if self.fail:
            raise GitHubError("no label")
        self.created.append((title, tuple(labels)))
        return 77

    def pr_comments(self, repo, number):
        return self.comments

    def comment(self, repo, number, path):
        self.posted.append((number, path.read_text()))


def test_write_creates_when_none_open():
    gh = _Gh()
    signals.write(gh, "travism26/harness-lab", _event())
    assert gh.created == [("Factory signals", ("factory:signals",))]
    assert gh.posted[0][0] == 77


def test_write_appends_to_lowest_and_only_once():
    gh = _Gh(issues=[8, 5])
    signals.write(gh, "travism26/harness-lab", _event())
    assert [n for n, _ in gh.posted] == [5] and not gh.created
    mark, _ = signals.entry(_event())
    gh.comments = [{"body": mark, "user": {"login": BOT}}]
    signals.write(gh, "travism26/harness-lab", _event())
    assert len(gh.posted) == 1


def test_write_swallows_github_errors(capsys):
    signals.write(_Gh(fail=True), "o/r", _event())
    assert "warning" in capsys.readouterr().out


class FakeGitHub(_Gh):
    """A step's GitHub: ticket comments in `posted`, signal comments in `signals`."""

    def __init__(self, issue=None, pr=None):
        super().__init__(issues=[900])
        self._issue, self._pr = issue, pr
        self.added, self.removed, self.signals = [], [], []

    def issue(self, repo, number):
        return self._issue

    def pr(self, repo, number):
        return self._pr

    def comment(self, repo, number, path):
        (self.signals if number == 900 else self.posted).append(
            path.read_text() if number == 900 else (number, path.read_text())
        )

    def add_labels(self, repo, number, labels):
        self.added += list(labels)

    def remove_labels(self, repo, number, labels):
        self.removed += list(labels)

    def open_issues_labelled(self, repo, label):
        return [900] if label == "factory:signals" else []


def _args(tmp_path, **kw):
    base = {
        "repo": "travism26/harness-lab",
        "issue": 4,
        "pr": 9,
        "out": str(tmp_path / "out"),
        "run_url": "https://github.com/o/r/actions/runs/55",
    }
    base.update(kw)
    return argparse.Namespace(**base)


def _issue():
    return {"labels": [{"name": "factory:in-progress"}]}


def _pr():
    return {"labels": []}


def test_release_records_an_implement_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "55")
    gh = FakeGitHub(issue=_issue())
    assert ticket.release(_args(tmp_path), gh) == 0
    assert len(gh.signals) == 1
    assert "<!-- factory:signal implement-failed-4-55 -->" in gh.signals[0]
    assert len(gh.posted) == 1


def test_release_unchanged_when_the_write_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "55")
    ok = FakeGitHub(issue=_issue())
    ticket.release(_args(tmp_path), ok)
    bad = FakeGitHub(issue=_issue())

    def boom(*a, **k):
        raise GitHubError("x")

    bad.create_issue = bad.open_issues_labelled = boom
    assert ticket.release(_args(tmp_path), bad) == 0
    assert bad.posted == ok.posted
    assert bad.added == ok.added and bad.removed == ok.removed


def test_fail_pr_records_text_none_and_the_run_url(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_RUN_ID", "66")
    gh = FakeGitHub(pr=_pr())
    ticket.fail_pr(_args(tmp_path), gh)
    assert "- Text: none" in gh.signals[0]
    assert "https://github.com/o/r/actions/runs/66" in gh.signals[0]
    assert "rework-failed-9-66" in gh.signals[0]


@pytest.mark.parametrize(
    "body,expected", [("Retry: please", 1), ("retry", 0), ("hi\nRetry:", 0)]
)
def test_only_a_retry_first_line_is_a_signal(monkeypatch, body, expected):
    monkeypatch.setenv("GITHUB_RUN_ID", "70")
    gh = FakeGitHub(issue={"labels": []})
    picker.retry_issue(gh, "travism26/harness-lab", 4, body)
    assert len(getattr(gh, "signals", [])) == expected
    if expected:
        assert "retry-4-70" in gh.signals[0]


def test_a_lock_held_retry_is_still_a_signal(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "71")
    gh = FakeGitHub(issue={"labels": []})
    monkeypatch.setattr(picker, "lock_held", lambda issues: True)
    monkeypatch.setattr(picker, "load_open", lambda gh, repo: [])
    gh.issue_fields = lambda *a: {}
    picker.retry_issue(gh, "travism26/harness-lab", 4, "Retry:")
    assert "retry-4-71" in gh.signals[0]
    assert gh.added == []


def test_the_label_row_is_factory_applied_and_short():
    row = next(x for x in load_labels() if x.name == "factory:signals")
    assert row.description.startswith("Factory-applied:")
    assert len(row.description) <= 100
