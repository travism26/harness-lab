import os
from pathlib import Path

from factory.check import LABEL as CHECK_LABEL
from factory.review_pr import MAX_REWORK, REWORK_LABEL, STOPPED_LABEL
from factory.sync_labels import Label, command_for, describe, load_labels, plan_changes
from factory.ticket import FAILED_LABEL, PROGRESS_LABEL, START_LABEL


def test_the_set_holds_every_label_the_factory_uses():
    names = {label.name for label in load_labels()}
    used = {
        START_LABEL,
        PROGRESS_LABEL,
        FAILED_LABEL,
        REWORK_LABEL,
        STOPPED_LABEL,
        CHECK_LABEL,
        "project:harness",
        "project:agent-identity",
        "factory:standards",
        "owner:retro",
        *(f"factory:rework-{n}" for n in range(1, MAX_REWORK + 1)),
    }
    assert used <= names


def test_the_set_holds_the_triage_labels():
    names = {label.name for label in load_labels()}
    assert {
        "needs-triage",
        "needs-info",
        "ready-for-agent",
        "ready-for-human",
        "wontfix",
    } <= names


def test_plan_creates_missing_and_updates_changed_labels_only():
    desired = [
        Label("a", "ffffff", "A"),
        Label("b", "000000", "B"),
        Label("c", "111111", "C"),
    ]
    existing = [
        Label("A", "FFFFFF", "A"),
        Label("b", "000000", "old"),
        Label("zzz", "1", ""),
    ]
    changes = plan_changes(desired, existing)
    assert [(c.action, c.label.name) for c in changes] == [
        ("update", "b"),
        ("create", "c"),
    ]


def test_every_project_with_a_check_has_a_project_row():
    names = {label.name for label in load_labels()}
    projects = Path(__file__).resolve().parents[2] / "projects"
    folders = [
        d
        for d in projects.iterdir()
        if (d / "check").is_file() and os.access(d / "check", os.X_OK)
    ]
    assert folders
    missing = sorted(d.name for d in folders if f"project:{d.name}" not in names)
    assert not missing


def test_the_set_holds_the_builder_and_wayfinder_labels():
    names = {label.name for label in load_labels()}
    assert {
        "scout:ready",
        "builder:claimed",
        "builder:spec-ready",
        "owner:implement",
        *(
            f"wayfinder:{k}"
            for k in ("map", "research", "grilling", "prototype", "task")
        ),
    } <= names


def test_clear_labels_workflow_has_no_secret_checkout_or_fork_path():
    text = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "clear-labels.yml"
    ).read_text()
    assert "secrets." not in text and "checkout" not in text
    assert "pull_request_target" not in text
    assert "github.event.pull_request.head.repo.full_name == github.repository" in text


def test_no_workflow_or_factory_code_names_the_issue_label():
    """`ready-for-human` is an issue label; the PR stop label is `factory-stopped`. One legacy
    definition in review_pr.py may name it."""
    root = Path(__file__).resolve().parents[2]
    files = [
        *(root / ".github" / "workflows").glob("*.yml"),
        *(root / "factory").glob("*.py"),
    ]
    assert files
    hits = [
        f"{f.relative_to(root)}:{n}"
        for f in files
        for n, line in enumerate(f.read_text().splitlines(), 1)
        if "ready-for-human" in line and not line.startswith("LEGACY_STOPPED_LABEL = ")
    ]
    assert not hits


def test_every_label_description_is_at_most_githubs_100_character_limit():
    """GitHub rejects a label description longer than 100 characters (HTTP 422)."""
    too_long = [
        f"{label.name} ({len(label.description)})"
        for label in load_labels()
        if len(label.description) > 100
    ]
    assert not too_long


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _workflow(name: str) -> str:
    return (_root() / ".github" / "workflows" / name).read_text()


def _step(text: str, name: str) -> str:
    return text.split(f"name: {name}", 1)[1].split("\n      - name:", 1)[0]


def test_rename_plan_edits_the_old_name_without_create_or_delete():
    desired = [Label("factory:in-progress", "fbca04", "Factory-applied: the lock")]
    existing = [Label("in-progress", "aaaaaa", "old text")]
    changes = plan_changes(desired, existing, [("in-progress", "factory:in-progress")])
    assert [change.action for change in changes] == ["rename"]
    command = command_for(changes[0], "travism26/harness-lab")
    assert command[:3] == ["label", "edit", "in-progress"]
    assert command[command.index("--name") + 1] == "factory:in-progress"
    assert "create" not in command and "delete" not in command
    assert all(change.action not in ("create", "delete") for change in changes)


def test_rename_plan_when_both_names_exist_deletes_nothing():
    desired = [Label("factory:in-progress", "fbca04", "Factory-applied: the lock")]
    existing = [
        Label("in-progress", "fbca04", "old text"),
        Label("factory:in-progress", "000000", "stale"),
    ]
    changes = plan_changes(desired, existing, [("in-progress", "factory:in-progress")])
    assert all(change.action != "delete" for change in changes)
    assert not any(change.action == "rename" for change in changes)
    assert any(
        change.action == "update" and change.label.name == "factory:in-progress"
        for change in changes
    )
    assert "left" in " ".join(describe(change) for change in changes)
    for change in changes:
        if change.action == "leave":
            continue
        assert "delete" not in command_for(change, "o/r")


def test_rename_plan_when_only_the_new_name_exists_plans_nothing_for_the_pair():
    desired = [Label("factory:in-progress", "fbca04", "Factory-applied: the lock")]
    existing = [Label("factory:in-progress", "fbca04", "Factory-applied: the lock")]
    changes = plan_changes(desired, existing, [("in-progress", "factory:in-progress")])
    assert changes == []


def test_label_set_or_app_start_prefixes_and_review_events():
    triage = {
        "needs-triage",
        "needs-info",
        "ready-for-agent",
        "ready-for-human",
        "wontfix",
    }
    prefixes = ("owner:", "builder:", "scout:", "factory:")
    names = set()
    for label in load_labels():
        names.add(label.name)
        assert len(label.description) <= 100
        assert (
            label.name in triage
            or label.name.startswith("wayfinder:")
            or label.name.startswith("project:")
            or label.name.startswith(prefixes)
        ), label.name
    assert "ready-for-factory" not in names
    assert "owner:review" not in names

    implement = _workflow("implement.yml")
    assert "ready-for-factory" not in implement
    assert "factory:start" in implement
    assert "format('{0}-factory[bot]', github.repository_owner)" in implement
    assert "!github.event.issue.pull_request" in implement
    assert "'factory-ticket'" in implement

    review = _workflow("review.yml")
    events = review.split("types:", 1)[1].split("]", 1)[0]
    for event in ("opened", "synchronize", "reopened", "ready_for_review"):
        assert event in events
    review_if = review.split("  review:", 1)[1].split("if:", 1)[1]
    review_if = review_if.split("runs-on:", 1)[0]
    assert "label" not in review_if


def test_clear_labels_colon_is_encoded_and_old_names_stay():
    text = _workflow("clear-labels.yml")
    assert "secrets." not in text
    assert "factory%3Ain-progress" in text
    assert "factory%3Arework" in text
    assert 'index("in-progress")' in text or "index('in-progress')" in text
    assert 'index("rework")' in text or "index('rework')" in text


def test_factory_start_token_is_the_app_and_picker_skips_preflight():
    picker = _workflow("picker.yml")
    retry = _workflow("retry.yml")
    assert "factory-preflight" not in picker
    for text in (picker, retry):
        step = _step(text, "Add factory:start")
        assert "factory:start" in text
        assert "steps.app.outputs.token" in step
        assert "github.token" not in step
    release = _step(_workflow("implement.yml"), "Hand the Ticket back after a failure")
    assert "steps.preflight.outputs.token" in release
    assert "github.token" not in release
    gate = _step(_workflow("ci-gate.yml"), "Post the finding and move the labels")
    assert "steps.preflight.outputs.token" in gate
    assert "github.token" not in gate
