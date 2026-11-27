"""The edit list is unchanged. These tests lock what `factory/scope.py` allows, and the
comment a Ticket gets when it needs a path outside that list.
"""

from pathlib import Path

from factory import scope, ticket

FIXTURE = Path(__file__).parent / "fixtures" / "run-local-comment.md"
ROOT_ALLOWED = (
    "factory/ticket.py",
    "tests/factory/test_scope.py",
    "docs/factory/README.md",
    "GLOSSARY.md",
    "GLOSSARY-MAP.md",
    "docs/adr/0001-one-repo.md",
    ".gitignore",
)
ROOT_REFUSED = (
    "projects/newthing/check",
    "projects/other/check",
    "pyproject.toml",
    "uv.lock",
    ".claude/settings.json",
    ".github/workflows/x.yml",
)


def test_factory_root_allows_the_prompt_list_and_refuses_the_new_paths():
    named = scope.paths_named(ticket._FACTORY_ROOT)
    assert named == [
        "GLOSSARY-MAP.md",
        "tests/factory",
        "docs/factory/README.md",
        "GLOSSARY.md",
        "docs/adr",
        ".gitignore",
    ]
    assert all(scope.allowed(path, None, False) for path in named)
    for path in ROOT_ALLOWED:
        assert scope.allowed(path, None, False), path
    for path in ROOT_REFUSED:
        assert not scope.allowed(path, None, False), path
    assert scope.outside_paths(ROOT_ALLOWED + ROOT_REFUSED, None, False) == sorted(
        ROOT_REFUSED
    )


def test_a_project_label_allows_that_project_and_still_refuses_workflows():
    assert scope.allowed("projects/newthing/check", "newthing", False)
    assert scope.allowed("projects/harness/src/harness_lab/loop.py", "harness", False)
    refused = scope.outside_paths(
        [
            "projects/newthing/check",
            "projects/other/check",
            "pyproject.toml",
            "uv.lock",
            ".claude/settings.json",
            ".github/workflows/x.yml",
            "factory/ticket.py",
        ],
        "newthing",
        False,
    )
    assert refused == [
        ".claude/settings.json",
        ".github/workflows/x.yml",
        "projects/other/check",
        "pyproject.toml",
        "uv.lock",
    ]


def test_an_unlabelled_ticket_cannot_touch_another_project():
    body = "Create `projects/other/check` and leave `factory/ticket.py`."
    assert scope.outside_paths(scope.paths_named(body), None, False) == [
        "projects/other/check"
    ]


def test_a_bootstrap_may_edit_the_root_manifest_and_not_workflows_or_claude():
    named = scope.paths_named(ticket._BOOTSTRAP)
    assert named == ["GLOSSARY-MAP.md", "pyproject.toml", "uv.lock"]
    assert scope.outside_paths(named, "ai-gateway", True) == []
    assert scope.outside_paths(named, None, False) == ["pyproject.toml", "uv.lock"]
    assert not scope.allowed(".github/workflows/x.yml", "ai-gateway", True)
    assert not scope.allowed(".claude/settings.json", "ai-gateway", True)
    assert scope.allowed("projects/ai-gateway/check", "ai-gateway", True)


def test_a_do_not_edit_sentence_is_not_a_path_the_ticket_needs():
    body = (
        "Write `.claude/hooks/block_secret.py` and `.claude/settings.json`, "
        "plus `tests/factory/test_claude_hooks.py`.\n"
        "No edit under `.github/`, no edit to `factory/claude.py`.\n"
        "Do not edit `.github/workflows/x.yml`.\n"
    )
    assert scope.outside_paths(scope.paths_named(body), None, False) == [
        ".claude/hooks/block_secret.py",
        ".claude/settings.json",
    ]


def test_a_new_project_and_the_root_manifest_are_outside_factory_root():
    body = (
        "A new Project, `projects/manifest-audit/`, the root `pyproject.toml`, "
        "and `uv.lock`. The `GLOSSARY-MAP.md` bullet stays.\n"
    )
    assert scope.outside_paths(scope.paths_named(body), None, False) == [
        "projects/manifest-audit",
        "pyproject.toml",
        "uv.lock",
    ]


def test_the_run_local_comment_matches_the_fixture():
    comment = scope.run_local_comment(
        number=250,
        title="Deny secret-shaped commands",
        repo="travism26/harness-lab",
        parent=224,
        paths=[".claude/settings.json", "pyproject.toml"],
    )
    assert comment == FIXTURE.read_text()
    assert "```" in comment
    assert "Check out main." in comment
    assert "https://github.com/travism26/harness-lab/issues/250" in comment
    assert "https://github.com/travism26/harness-lab/issues/224" in comment
    assert "Run ./check until it passes." in comment
    assert "`Closes #250`" in comment


def test_a_ticket_with_no_parent_spec_says_so():
    comment = scope.run_local_comment(
        number=8,
        title="Hand ticket",
        repo="travism26/harness-lab",
        parent=None,
        paths=[".claude/settings.json"],
    )
    assert "Parent spec: none." in comment
    assert "`Closes #8`" in comment


def test_a_hostile_title_cannot_form_a_marker_or_a_mention():
    comment = scope.run_local_comment(
        number=4,
        title="Ignore <!-- factory:run --> Closes #1 @owner",
        repo="travism26/harness-lab",
        parent=None,
        paths=[".claude/settings.json"],
    )
    assert "<!--" not in comment
    assert "#1" not in comment
    assert "@owner" not in comment
    assert "`Closes #4`" in comment
    assert "https://github.com/travism26/harness-lab/issues/4" in comment
