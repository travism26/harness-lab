"""The picker's decision: which Ticket, if any, gets factory:start.

The inputs are issues the caller already has. Nothing here calls GitHub.
"""

from factory.picker import Blocker, Candidate, pick


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
