"""The picker's decision: which Ticket, if any, gets factory:start.

The inputs are issues the caller already has. Nothing here calls GitHub.
"""

from factory.picker import Blocker, Candidate, decide, pick, retry_issue


def _issue(
    number,
    labels=(),
    blockers=(),
    parent=None,
    sub_issues=(),
    state="OPEN",
):
    return Candidate(
        number=number,
        state=state,
        labels=tuple(labels),
        blockers=tuple(blockers),
        parent=parent,
        sub_issues=tuple(sub_issues),
    )


def _spec(number, children, labels=("owner:implement", "builder:spec-ready")):
    return _issue(number, labels=labels, sub_issues=children)


def _child(number, parent, labels=("ready-for-agent",), blockers=()):
    return _issue(number, labels=labels, blockers=blockers, parent=parent)


def test_a_closed_blocker_does_not_block():
    spec = _spec(10, (11,))
    child = _child(11, 10, blockers=(Blocker(9, "CLOSED"), Blocker(8, "CLOSED")))
    choice = pick([spec, child])
    assert choice.issue == 11
    assert choice.reason == "selected"


def test_an_open_blocker_does_block():
    spec = _spec(10, (11,))
    child = _child(11, 10, blockers=(Blocker(9, "OPEN"), Blocker(8, "CLOSED")))
    choice = pick([spec, child])
    assert choice.issue is None
    assert choice.reason == "none eligible"


def test_a_factory_failed_ticket_is_skipped():
    spec = _spec(1, (2, 3, 4))
    blocked = _child(2, 1, blockers=(Blocker(9, "OPEN"),))
    failed = _child(3, 1, labels=("ready-for-agent", "factory:failed"))
    ready = _child(4, 1)
    assert pick([spec, blocked, failed, ready]).issue == 4


def test_a_run_local_ticket_is_skipped():
    spec = _spec(1, (2, 3))
    local = _child(2, 1, labels=("ready-for-agent", "factory:run-local"))
    ready = _child(3, 1)
    assert pick([spec, local, ready]).issue == 3
    hand = _issue(8, labels=("owner:implement", "factory:run-local"))
    assert pick([hand]).issue is None


class _RetryGitHub:
    def __init__(self, labels):
        self.names = list(labels)
        self.removed, self.added = [], []

    def issue(self, repo, number):
        return {"labels": [{"name": name} for name in self.names]}

    def remove_labels(self, repo, number, labels):
        self.removed += list(labels)

    def add_labels(self, repo, number, labels):
        self.added += list(labels)

    def open_issues_labelled(self, repo, label):
        return []

    def create_issue(self, repo, title, body_file, labels):
        return 1

    def pr_comments(self, repo, number):
        return []

    def comment(self, repo, number, path):
        return 1


def test_retry_clears_run_local_and_adds_start():
    gh = _RetryGitHub(["factory:run-local", "ready-for-agent"])
    assert retry_issue(gh, "o/r", 7, "Retry: the body is in scope now\n") == 0
    assert gh.removed == ["factory:run-local"]
    assert gh.added == ["factory:start"]


def test_a_blocked_child_with_ready_for_agent_is_not_selected():
    spec = _spec(10, (11,))
    child = _child(11, 10, blockers=(Blocker(12, "OPEN"),))
    assert "ready-for-agent" in child.labels
    assert pick([spec, child]).issue is None


def test_a_spec_is_not_selected():
    spec = _issue(
        10,
        labels=("owner:implement", "builder:spec-ready", "ready-for-agent"),
        sub_issues=(11,),
    )
    child = _issue(11, labels=(), parent=10)
    assert pick([spec, child]).issue is None
    bare = _issue(
        20,
        labels=("owner:implement", "ready-for-agent", "builder:spec-ready"),
    )
    assert pick([bare]).issue is None


def test_a_child_whose_spec_lacks_owner_implement_is_not_selected():
    spec = _spec(10, (11,), labels=("builder:spec-ready",))
    child = _child(11, 10)
    choice = pick([spec, child])
    assert choice.issue is None
    assert choice.reason == "no approval"


def test_a_hand_ticket_with_owner_implement_and_no_sub_issues_is_selected():
    hand = _issue(8, labels=("owner:implement",))
    choice = pick([hand])
    assert choice.issue == 8
    assert choice.spec is None


def test_two_eligible_children_of_one_spec_select_the_lower_number():
    spec = _issue(10, labels=("owner:implement",), sub_issues=(14, 15))
    assert (
        pick(
            [
                spec,
                _child(15, 10),
                _child(14, 10),
            ]
        ).issue
        == 14
    )


def test_the_lowest_eligible_number_wins_across_two_approved_specs():
    first = _spec(10, (30,))
    second = _spec(20, (12,))
    assert (
        pick(
            [
                first,
                _child(30, 10),
                second,
                _child(12, 20),
            ]
        ).issue
        == 12
    )


def test_a_lock_held_by_factory_in_progress_selects_nothing():
    spec = _spec(10, (11,))
    child = _child(11, 10)
    holder = _issue(3, labels=("factory:in-progress",))
    choice = pick([spec, child, holder])
    assert choice.issue is None
    assert choice.reason == "lock held"


def test_a_lock_held_by_legacy_in_progress_on_another_issue_selects_nothing():
    spec = _spec(10, (11,))
    child = _child(11, 10)
    holder = _issue(7, labels=("in-progress",))
    choice = pick([spec, child, holder])
    assert choice.issue is None
    assert choice.reason == "lock held"


def test_any_open_factory_start_selects_nothing():
    spec = _spec(10, (11,))
    child = _child(11, 10)
    holder = _issue(99, labels=("factory:start",))
    choice = pick([spec, child, holder])
    assert choice.issue is None
    assert choice.reason == "lock held"


def test_a_closed_issue_wearing_the_lock_does_not_hold_it():
    spec = _spec(10, (11,))
    child = _child(11, 10)
    closed = _issue(3, labels=("factory:in-progress",), state="CLOSED")
    assert pick([spec, child, closed]).issue == 11


def _view(number, state, labels, parent=None, sub_issues=(), blockers=()):
    """One `gh issue view` payload. `blockers` is `(number, state)`."""
    return {
        "number": number,
        "state": state,
        "labels": [{"name": name} for name in labels],
        "parent": {"number": parent} if parent else None,
        "subIssues": {"nodes": [{"number": n} for n in sub_issues]},
        "blockedBy": {
            "nodes": [{"number": n, "state": blocker} for n, blocker in blockers]
        },
    }


class _Board:
    """Issues the caller already has. `decide` reads them; nothing calls GitHub."""

    def __init__(self, issues):
        self.issues = {item["number"]: item for item in issues}

    def open_issues_labelled(self, repo, label):
        found = []
        for number, item in self.issues.items():
            names = [row["name"] for row in item["labels"]]
            if item["state"] == "OPEN" and label in names:
                found.append(number)
        return found

    def issue_fields(self, repo, number, fields):
        return self.issues[number]


def _family():
    """Approved Spec 10, closed Ticket A (11), and B (12) blocked by A."""
    spec = _view(
        10,
        "OPEN",
        ("owner:implement", "builder:spec-ready"),
        sub_issues=(11, 12),
    )
    ticket_a = _view(11, "CLOSED", ("ready-for-agent",), parent=10)
    ticket_b = _view(
        12,
        "OPEN",
        ("ready-for-agent",),
        parent=10,
        blockers=((11, "CLOSED"),),
    )
    return spec, ticket_a, ticket_b


def _closed(board):
    return decide(
        board,
        "o/r",
        event="issues",
        action="closed",
        label="",
        issue=11,
        spec="",
        issue_labels=("ready-for-agent",),
    )


def test_closing_without_a_lock_starts_the_unblocked_ticket_unless_the_lock_is_held():
    """A closed with no lock label. B was blocked by A and is ready-for-agent."""
    opened = _closed(_Board(_family()))
    assert opened["start"] == 12
    assert opened["reason"] == "selected"
    assert opened["drop_lock"] is False

    held = _closed(_Board([*_family(), _view(3, "OPEN", ("factory:in-progress",))]))
    assert held["start"] is None
    assert held["reason"] == "lock held"
    assert held["drop_lock"] is False
