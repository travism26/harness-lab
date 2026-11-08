from factory.review_pr import HUMAN_LABEL, MAX_REWORK, REWORK_LABEL
from factory.sync_labels import Label, load_labels, plan_changes
from factory.ticket import PROGRESS_LABEL, START_LABEL
from factory.check import LABEL as CHECK_LABEL


def test_the_set_holds_every_label_the_factory_uses():
    names = {label.name for label in load_labels()}
    used = {START_LABEL, PROGRESS_LABEL, REWORK_LABEL, HUMAN_LABEL, CHECK_LABEL,
            "project:harness", "project:agent-identity",
            *(f"rework:{n}" for n in range(1, MAX_REWORK + 1))}
    assert used <= names


def test_the_set_holds_the_triage_labels():
    names = {label.name for label in load_labels()}
    assert {"needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix"} <= names


def test_plan_creates_missing_and_updates_changed_labels_only():
    desired = [Label("a", "ffffff", "A"), Label("b", "000000", "B"), Label("c", "111111", "C")]
    existing = [Label("A", "FFFFFF", "A"), Label("b", "000000", "old"), Label("zzz", "1", "")]
    changes = plan_changes(desired, existing)
    assert [(c.action, c.label.name) for c in changes] == [("update", "b"), ("create", "c")]
