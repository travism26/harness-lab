"""The owner Override: the comment parser, what it sets, and the workflow's shape."""

from pathlib import Path

import pytest

from factory import override
from factory.override import LABEL, apply, parse_override
from tests.factory.support import REPO, SHA, FakeGitHub

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github" / "workflows" / "override.yml").read_text()
SETUP = (ROOT / "docs" / "factory" / "setup.md").read_text()
GATE = SETUP.split("## Turning on the gate")[1].split("\n## ")[0]
URL = f"https://github.com/{REPO}/pull/9#issuecomment-5"
REASON = "the reviewer is wrong about the cap, ship it"


def test_an_override_with_a_reason_is_accepted() -> None:
    assert parse_override("Override: reason here") == "reason here"
    assert parse_override("Override:   spaced  \nmore text") == "spaced"


@pytest.mark.parametrize(
    "body",
    [
        "Override:",
        "Override:   ",
        "override: reason",
        "OVERRIDE: reason",
        "thanks\nOverride: reason",
        " Override: reason",
        "Please Override: reason",
        "",
    ],
)
def test_other_comments_are_rejected(body: str) -> None:
    assert parse_override(body) is None


class Statuses:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def __call__(self, sha: str, state: str, description: str, url: str) -> None:
        self.calls.append((sha, state, description, url))


def test_an_override_sets_success_on_the_current_head_and_labels_the_pr() -> None:
    gh, statuses = FakeGitHub(), Statuses()
    assert apply(gh, REPO, 9, f"Override: {REASON}", URL, statuses) == 0
    assert statuses.calls == [(SHA, "success", "Overridden by the owner", URL)]
    assert gh.labels == [LABEL]


def test_no_status_description_contains_the_reason() -> None:
    gh, statuses = FakeGitHub(), Statuses()
    apply(gh, REPO, 9, f"Override: {REASON}", URL, statuses)
    assert all(REASON not in c[2] and REASON not in c[3] for c in statuses.calls)


def test_a_rejected_comment_changes_nothing() -> None:
    gh, statuses = FakeGitHub(), Statuses()
    assert apply(gh, REPO, 9, "Override:", URL, statuses) == 0
    assert statuses.calls == [] and gh.labels == []


def test_the_pull_request_is_read_with_the_rest_api_not_gh_pr_view() -> None:
    class RestOnly(FakeGitHub):
        def pr(self, repo, number):
            raise AssertionError("gh pr view needs pull-requests: read")

    gh, statuses = RestOnly(), Statuses()
    apply(gh, REPO, 9, f"Override: {REASON}", URL, statuses)
    assert [c[0] for c in statuses.calls] == [SHA]


def test_a_closed_pull_request_is_left_alone() -> None:
    gh, statuses = FakeGitHub(state="MERGED"), Statuses()
    apply(gh, REPO, 9, "Override: late", URL, statuses)
    assert statuses.calls == [] and gh.labels == []


def test_an_override_works_with_no_review_comment_as_on_a_fork_pr() -> None:
    # The fake PR knows only its state and head sha, and has no Review comment: a fork PR.
    head = "f" * 40
    gh, statuses = FakeGitHub(comments=(), head=head), Statuses()
    apply(gh, REPO, 9, "Override: fork contribution", URL, statuses)
    assert [c[0] for c in statuses.calls] == [head]
    assert "head.repo" not in WORKFLOW


def test_the_workflow_runs_only_on_a_created_owner_comment_on_a_pull_request() -> None:
    assert "issue_comment:\n    types: [created]" in WORKFLOW
    assert "github.event.issue.pull_request" in WORKFLOW
    assert "github.event.sender.login == github.repository_owner" in WORKFLOW
    assert "\npermissions: {}" in WORKFLOW


def test_the_workflow_holds_no_agent_secret_or_pr_code() -> None:
    for banned in (
        "pull_request_target",
        "ref:",
        "claude",
        "secrets.",
        "factory-preflight",
    ):
        assert banned not in WORKFLOW
    assert "github.event.comment.body" in WORKFLOW
    run_lines = [ln for ln in WORKFLOW.splitlines() if "run:" in ln]
    assert all("comment.body" not in ln for ln in run_lines)


def test_the_label_is_in_the_label_set() -> None:
    assert override.LABEL == "factory:override"
    assert '"factory:override"' in (ROOT / "factory" / "labels.json").read_text()


@pytest.mark.parametrize(
    "text",
    ["Override: <reason>", "case-sensitive", "factory:override", "head", "overwrite"],
)
def test_the_setup_doc_explains_the_override(text: str) -> None:
    assert text in GATE
