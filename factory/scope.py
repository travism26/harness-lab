"""Whether a path is inside the factory's allowed edit list.

The list is the one the build prompts already state (`factory/ticket.py`):

- every Ticket: `factory/`, `tests/factory/`, `docs/factory/README.md`, `GLOSSARY.md`,
  `GLOSSARY-MAP.md`, `docs/adr/`, `.gitignore`;
- a Ticket with `project:<name>`: `projects/<name>/` as well;
- a bootstrap (the name is registered and `projects/<name>/check` is not there yet):
  the root `pyproject.toml` and `uv.lock` as well.

`.github/` stays outside, including `.github/workflows/`. This module does not widen
that list. It decides when a Ticket needs something outside it.
"""

import re
from collections.abc import Iterable

from factory.github import neutralize, neutralize_comments

# Same slug `factory/ticket.py` accepts on a `project:` label.
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# A directory the prompts allow, or a file named exactly.
_PREFIXES = ("factory", "tests/factory", "docs/adr")
_EXACT = frozenset(
    {
        "docs/factory/README.md",
        "GLOSSARY.md",
        "GLOSSARY-MAP.md",
        ".gitignore",
    }
)
# Only a bootstrap prompt allows these. An ordinary Ticket that names them is outside.
_BOOTSTRAP_FILES = frozenset({"pyproject.toml", "uv.lock"})
# Root files a Ticket body can name without a slash. `README.md` and `CLAUDE.md` are
# not here: a bare name is usually the Project's file, not the repo root.
_ROOT_FILES = _EXACT | _BOOTSTRAP_FILES
_TOP = re.compile(
    r"^(?:factory|tests|docs|projects|experiments|\.claude|\.github)(?:/[\w.@+-]+)*$"
)
_TICK = re.compile(r"`([^`\n]+)`")
# A sentence that tells the agent not to edit is not a path the Ticket needs.
_NEGATION = re.compile(
    r"(?i)\b(?:do not|don't|dont|must not|never|no)\s+edit\b|\bwithout editing\b"
)


def _clean(raw: str) -> str:
    path = (raw or "").strip().strip('"').strip("'")
    while path.endswith((".", ",", ";", ":", ")")):
        path = path[:-1]
    return path.removeprefix("./").rstrip("/")


def _broken(path: str) -> bool:
    if not path or path.startswith("/") or ".." in path.split("/"):
        return True
    return any(mark in path for mark in ("<", ">", "*", "{", "}", " ", "\n"))


def allowed(path: str, project: str | None, bootstrap: bool) -> bool:
    """True when the build prompt already lets the agent edit `path`."""
    cleaned = _clean(path)
    if _broken(cleaned):
        return False
    if cleaned in _EXACT or any(
        cleaned == root or cleaned.startswith(root + "/") for root in _PREFIXES
    ):
        return True
    if (
        project
        and _SLUG.fullmatch(project)
        and (
            cleaned == f"projects/{project}"
            or cleaned.startswith(f"projects/{project}/")
        )
    ):
        return True
    return bool(bootstrap and cleaned in _BOOTSTRAP_FILES)


def paths_named(text: str) -> list[str]:
    """Repo paths in backticks, in order, skipping a sentence that says not to edit.

    A path is a backtick token with a slash under a repo top-level directory, or one
    of the root files in the edit list plus `pyproject.toml` and `uv.lock`.
    """
    found: list[str] = []
    for sentence in re.split(r"\n+|(?<=[.!?])\s+", text or ""):
        if _NEGATION.search(sentence):
            continue
        for match in _TICK.finditer(sentence):
            path = _clean(match.group(1))
            if _broken(path) or path in found:
                continue
            named = path in _ROOT_FILES or (
                "/" in path and _TOP.fullmatch(path) is not None
            )
            if named:
                found.append(path)
    return found


def outside_paths(
    paths: Iterable[str], project: str | None, bootstrap: bool
) -> list[str]:
    """`paths` the edit list does not allow, sorted, each once."""
    found: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        cleaned = _clean(str(raw))
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        if not allowed(cleaned, project or None, bootstrap):
            found.append(cleaned)
    return sorted(found)


def _show(path: str) -> str:
    return neutralize_comments(path.replace("`", "").replace("\n", " "))


def _title(title: str) -> str:
    flat = " ".join((title or "").split()).replace("`", "")
    return neutralize(flat) or "this Ticket"


def issue_url(repo: str, number: int) -> str:
    return f"https://github.com/{repo}/issues/{number}"


def run_local_comment(
    *,
    number: int,
    title: str,
    repo: str,
    parent: int | None,
    paths: Iterable[str],
) -> str:
    """The one Ticket comment: why the factory stopped, then a prompt to paste into Claude Code."""
    shown = ", ".join(f"`{_show(path)}`" for path in paths)
    url = issue_url(repo, number)
    if parent is None:
        parent_line = "Parent spec: none."
    else:
        parent_line = f"Parent spec: #{parent} ({issue_url(repo, parent)})."
    prompt = (
        f'Check out main. Implement issue #{number} ({url}), "{_title(title)}", '
        f"per its acceptance criteria. {parent_line} "
        f"Paths outside the allowed list: {shown}. "
        f"Run ./check until it passes. "
        f"Open a pull request with `Closes #{number}`."
    )
    return (
        "The factory stopped. This Ticket needs edits outside the allowed list: "
        f"{shown}.\n\n```\n{prompt}\n```\n"
    )
