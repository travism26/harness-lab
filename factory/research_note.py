"""The publish gate of the factory's research path: check one research note file.

It checks one note under `docs/research/notes/` (docs/factory/README.md, "Research path"): the
required sections, tagged `https://` sources, a stated unknowns section, the cost line and its cap,
and no credential-shaped string. It reads the file and nothing else: it calls no model, no network
and no GitHub API. A problem message never repeats text from the note, because the problem list is
posted in a public GitHub comment and the note is model-written.

    uv run python -m factory.research_note docs/research/notes/issue-<N>.md
"""

import argparse
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

REQUIRED = ("Question", "Findings", "Sources", "Unknowns", "Cost")
TAGS = ("vendor", "independent")
COST_NOTE = "client-estimate"
# The first two lines of this pattern are a verbatim copy of `factory.record.TOKEN_RE.pattern`. The
# checker imports only the standard library, so it holds its own copy;
# tests/factory/test_research_note.py checks the copy has not drifted.
CREDENTIAL_RE = re.compile(
    r"sk-(?:ant|or)-|\bsk-[A-Za-z0-9_-]{6,}|gh[pousr]_[A-Za-z0-9]{10,}"
    r"|github_pat_|xox[abposr]-|eyJ[A-Za-z0-9_-]{10,}"
    r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING_RE = re.compile(r"^## +(.+?)\s*$")
_URL_RE = re.compile(r"https://[^\s<>()\[\]]+")
_TAG_RE = re.compile(r"\[(vendor|independent)\]")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_LIST_MARKER_RE = re.compile(r"(?m)^\s*(?:[-*+]|\d+\.)(?=\s|$)")
_SPEND_RE = re.compile(r"Spend:\s*\$([0-9]+(?:\.[0-9]+)?)\s*\(" + COST_NOTE + r"\)")
_CAP_RE = re.compile(r"Cap:\s*\$([0-9]+(?:\.[0-9]+)?)")
_PLACEHOLDERS = ("", "none", "n/a", "na", "nothing", "tbd", "todo")


class Section(NamedTuple):
    heading: str  # text after "## ", stripped
    body: str  # the lines up to the next "## " heading (H3 and deeper stay in the body)
    line: int  # 1-based line number of the heading in the text


def strip_comments(text: str) -> str:
    """Blank every HTML comment but keep its newlines, so line numbers do not move."""
    return _COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def sections(text: str) -> list[Section]:
    """Every level-2 heading in order, with its body. A line in a fenced code block is no heading."""
    found: list[list] = []
    in_fence = False
    for number, line in enumerate(text.split("\n"), start=1):
        if line.startswith("```"):
            in_fence = not in_fence
        match = None if in_fence or line.startswith("```") else _HEADING_RE.match(line)
        if match:
            found.append([match.group(1), [], number])
        elif found:
            found[-1][1].append(line)
    return [
        Section(heading, "\n".join(body), number) for heading, body, number in found
    ]


def is_blank(body: str) -> bool:
    """True when nothing but whitespace is left once comments are gone."""
    return not strip_comments(body).strip()


def _amount(value: float) -> str:
    """Four decimals, trailing zeros dropped, never fewer than two."""
    text = format(value, ".4f").rstrip("0")
    whole, _, frac = text.partition(".")
    return "{}.{}".format(whole, frac.ljust(2, "0"))


def cost_section(spend_usd: float, cap_usd: float) -> str:
    """The body of a note's `## Cost` section, in the shape `check_text` accepts."""
    return f"- Spend: ${_amount(spend_usd)} ({COST_NOTE})\n- Cap: ${_amount(cap_usd)}"


def _is_placeholder(body: str) -> bool:
    flat = _LIST_MARKER_RE.sub("", body)
    flat = re.sub(r"[\s.!_]", "", flat).lower()
    return flat in _PLACEHOLDERS


def _source_problems(section: Section) -> list[str]:
    problems: list[str] = []
    valid = 0
    for index, line in enumerate(section.body.split("\n")):
        if not line.strip():
            continue
        number = section.line + 1 + index
        has_url = bool(_URL_RE.search(line))
        tags = set(_TAG_RE.findall(line))
        if "http://" in line:
            problems.append(
                f"Sources line {number}: an `http://` URL; a source must be `https://`"
            )
        elif _LIST_ITEM_RE.match(line) and not has_url:
            problems.append(f"Sources line {number}: no `https://` URL")
        elif has_url and not tags:
            problems.append(
                f"Sources line {number}: the source is not tagged `[vendor]` or `[independent]`"
            )
        elif has_url and len(tags) > 1:
            problems.append(
                f"Sources line {number}: the source carries both tags; pick one"
            )
        elif has_url:
            valid += 1
    if not valid:
        problems.append("section `## Sources` lists no tagged `https://` source")
    return problems


def _cost_problems(body: str) -> list[str]:
    problems: list[str] = []
    spends = _SPEND_RE.findall(body)
    caps = _CAP_RE.findall(body)
    if not spends:
        problems.append(
            "section `## Cost` has no `Spend: $<number> (client-estimate)` line"
        )
    elif len(spends) > 1:
        problems.append("section `## Cost` has more than one Spend line")
    if not caps:
        problems.append("section `## Cost` has no `Cap: $<number>` line")
    elif len(caps) > 1:
        problems.append("section `## Cost` has more than one Cap line")
    if len(spends) == 1 and len(caps) == 1:
        if Decimal(caps[0]) <= 0:
            problems.append("the cap must be above zero")
        elif Decimal(spends[0]) > Decimal(caps[0]):
            problems.append(f"spend ${spends[0]} is over the cap ${caps[0]}")
    return problems


def check_text(text: str) -> list[str]:
    """The problems with a note; an empty list means it passes."""
    problems: list[str] = []
    found = sections(strip_comments(text))
    for name in REQUIRED:
        matches = [s for s in found if s.heading == name]
        if not matches:
            problems.append(f"missing section `## {name}`")
            continue
        if len(matches) > 1:
            problems.append(f"section `## {name}` appears more than once")
            continue
        section = matches[0]
        if name in ("Question", "Findings") and is_blank(section.body):
            problems.append(f"section `## {name}` is empty")
        elif name == "Unknowns" and (
            is_blank(section.body) or _is_placeholder(section.body)
        ):
            problems.append(
                "section `## Unknowns` is empty: say what could not be established"
            )
        elif name == "Sources":
            problems.extend(_source_problems(section))
        elif name == "Cost":
            problems.extend(_cost_problems(section.body))
    for number, line in enumerate(text.split("\n"), start=1):
        if CREDENTIAL_RE.search(line):
            problems.append(
                f"line {number}: a credential-shaped string; a note holds no secrets"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    """Check each file named; print one line per problem, or `ok`. 1 if any file failed."""
    parser = argparse.ArgumentParser(
        prog="factory.research_note", description=__doc__.split("\n")[0]
    )
    parser.add_argument("files", nargs="+", metavar="FILE")
    args = parser.parse_args(argv)
    failed = False
    for name in args.files:
        try:
            text = Path(name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            print(f"{name}: cannot be read")
            failed = True
            continue
        problems = check_text(text)
        for problem in problems:
            print(f"{name}: {problem}")
        if not problems:
            print(f"{name}: ok")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
