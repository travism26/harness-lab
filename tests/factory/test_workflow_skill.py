"""Keeps `.claude/skills/workflow/` in step with the board in `docs/skill-workflows.md`."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / "docs" / "skill-workflows.md"
SKILL = ROOT / ".claude" / "skills" / "workflow" / "SKILL.md"
TABLE = ROOT / ".claude" / "skills" / "workflow" / "scenarios.json"


def board_scenarios() -> list[str]:
    """The first column of the scenario table under "## 3. Scenarios"."""
    section = BOARD.read_text().split("## 3. Scenarios", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("|")]
    names = [row.split("|")[1].strip() for row in rows[2:]]  # skip header and rule
    assert names, "no scenario rows found in the board"
    return names


def test_skill_file_exists():
    assert SKILL.is_file(), f"missing {SKILL.relative_to(ROOT)}"


def test_every_board_scenario_is_in_the_table():
    have = {entry["name"] for entry in json.loads(TABLE.read_text())["scenarios"]}
    missing = [name for name in board_scenarios() if name not in have]
    assert not missing, f"scenarios.json is missing: {missing}"


def test_entries_are_complete():
    for entry in json.loads(TABLE.read_text())["scenarios"]:
        for field in ("key", "name", "flow", "when_to_use", "proof"):
            assert entry.get(field), f"{entry.get('key')}: empty {field}"
        assert all(step.get("step") for step in entry["flow"]), entry["key"]


def test_skill_names_the_command_and_the_skip_rule():
    text = SKILL.read_text()
    assert "/workflow" in text
    assert "skip: <reason>" in text


def board_skips() -> dict[str, list[str]]:
    """Each `###` scenario heading in section 3 mapped to the items of its `- Skip:` line."""
    section = BOARD.read_text().split("## 3. Scenarios", 1)[1].split("\n## ", 1)[0]
    skips = {}
    for block in section.split("\n### ")[1:]:
        name, _, body = block.partition("\n")
        skips[name.strip()] = []
        for line in body.splitlines():
            if line.startswith("- Skip:"):
                value = line.removeprefix("- Skip:").strip().rstrip(".")
                if value != "nothing":
                    skips[name.strip()] = [item.strip() for item in value.split(",")]
    return skips


def test_keys_are_unique_and_named_in_the_skill():
    keys = [entry["key"] for entry in json.loads(TABLE.read_text())["scenarios"]]
    assert len(keys) == len(set(keys)), "duplicate key in scenarios.json"
    text = SKILL.read_text()
    assert [key for key in keys if f"`{key}`" not in text] == []


def test_board_skip_items_reach_the_table():
    entries = {entry["name"]: entry for entry in json.loads(TABLE.read_text())["scenarios"]}
    assert all(isinstance(e.get("skip"), list) for e in entries.values())
    skips = board_skips()
    assert any(skips.values()), "no Skip lines parsed from the board"
    for name, items in skips.items():
        missing = [item for item in items if item not in entries[name]["skip"]]
        assert not missing, f"{name}: skip is missing {missing}"
