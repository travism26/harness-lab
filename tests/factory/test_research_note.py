import ast
import sys
from pathlib import Path

import pytest

from factory import research_note
from factory.record import TOKEN_RE
from factory.research_note import check_text, cost_section, main, strip_comments

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "research"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def good_with(old, new):
    text = fixture("good.md")
    assert old in text
    return text.replace(old, new)


def test_the_good_note_passes():
    assert check_text(fixture("good.md")) == []


@pytest.mark.parametrize(
    "name,problem",
    [
        ("missing-sources.md", "missing section `## Sources`"),
        ("missing-unknowns.md", "missing section `## Unknowns`"),
        (
            "empty-unknowns.md",
            "section `## Unknowns` is empty: say what could not be established",
        ),
        (
            "untagged-source.md",
            "Sources line 21: the source is not tagged `[vendor]` or `[independent]`",
        ),
        ("over-cap.md", "spend $2.31 is over the cap $2.00"),
    ],
)
def test_each_bad_fixture_gets_only_its_own_problem(name, problem):
    problems = check_text(fixture(name))
    assert problems == [problem]


def test_the_untagged_source_names_the_right_line():
    lines = fixture("untagged-source.md").split("\n")
    problems = check_text(fixture("untagged-source.md"))
    number = int(problems[0].split()[2].rstrip(":"))
    assert "example.org" in lines[number - 1]


# Built here so no file holds a credential-shaped string.
@pytest.mark.parametrize(
    "token",
    [
        "sk-ant-oat01-" + "x" * 30,
        "ghp_" + "a" * 36,
        "AKIA" + "A" * 16,
        "-----BEGIN RSA " + "PRIVATE KEY-----",
    ],
)
def test_a_credential_shaped_string_is_rejected_without_being_repeated(token):
    text = fixture("good.md") + "\nsome line " + token + "\n"
    number = len(text.split("\n")) - 1
    problems = check_text(text)
    assert problems == [
        f"line {number}: a credential-shaped string; a note holds no secrets"
    ]
    assert all(token not in p for p in problems)


def test_a_credential_hidden_in_a_comment_is_still_rejected():
    token = "ghp_" + "b" * 36
    problems = check_text(fixture("good.md") + "\n<!-- " + token + " -->\n")
    assert len(problems) == 1
    assert "a credential-shaped string" in problems[0]
    assert token not in problems[0]


def test_the_credential_pattern_has_not_drifted_from_the_record_pattern():
    assert TOKEN_RE.pattern in research_note.CREDENTIAL_RE.pattern


def test_the_checker_imports_only_the_standard_library():
    tree = ast.parse(
        (ROOT / "factory" / "research_note.py").read_text(encoding="utf-8")
    )
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            names.add(node.module.split(".")[0])
    assert names
    assert names <= set(sys.stdlib_module_names)
    assert not names & {
        "subprocess",
        "socket",
        "urllib",
        "http",
        "ssl",
        "ftplib",
        "smtplib",
        "asyncio",
    }


def test_an_http_source_is_rejected():
    text = good_with(
        "https://example.com/docs/widget:", "http://example.com/docs/widget:"
    )
    assert any(
        "an `http://` URL; a source must be `https://`" in p for p in check_text(text)
    )


def test_a_list_item_with_no_url_is_rejected():
    text = good_with(
        "- [vendor] https://example.com/docs/widget: the maker's own",
        "- [vendor] the maker's own",
    )
    assert any(p.endswith(": no `https://` URL") for p in check_text(text))


def test_a_source_with_both_tags_is_rejected():
    text = good_with("- [vendor] https", "- [vendor] [independent] https")
    assert any("carries both tags; pick one" in p for p in check_text(text))


def test_sources_with_no_items_is_rejected():
    text = good_with(
        "- [vendor] https://example.com/docs/widget: the maker's own description "
        "of the widget\n- [independent] https://example.org/reviews/widget: a review "
        "by someone who does not sell it\n",
        "Nothing here.\n",
    )
    assert check_text(text) == [
        "section `## Sources` lists no tagged `https://` source"
    ]


def test_spend_equal_to_the_cap_passes():
    assert check_text(good_with("$0.42", "$2.00")) == []


def test_a_spend_without_the_client_estimate_mark_is_rejected():
    problems = check_text(good_with(" (client-estimate)", ""))
    assert problems == [
        "section `## Cost` has no `Spend: $<number> (client-estimate)` line"
    ]


def test_a_missing_cap_line_is_rejected():
    problems = check_text(good_with("- Cap: $2.00", ""))
    assert problems == ["section `## Cost` has no `Cap: $<number>` line"]


def test_two_spend_lines_are_rejected():
    problems = check_text(
        good_with("- Cap:", "- Spend: $0.10 (client-estimate)\n- Cap:")
    )
    assert problems == ["section `## Cost` has more than one Spend line"]


def test_a_cap_of_zero_is_rejected():
    problems = check_text(good_with("- Cap: $2.00", "- Cap: $0").replace("$0.42", "$0"))
    assert problems == ["the cap must be above zero"]


def test_a_duplicated_section_is_reported_once_as_repeated():
    text = fixture("good.md") + "\n## Unknowns\n\nMore.\n"
    assert check_text(text) == ["section `## Unknowns` appears more than once"]


def test_a_sources_heading_inside_a_code_fence_is_not_the_section():
    text = fixture("missing-sources.md").replace("## Not a heading", "## Sources")
    assert check_text(text) == ["missing section `## Sources`"]


@pytest.mark.parametrize(
    "body", ["None", "- N/A", "TBD.", "<!-- say something here -->", ""]
)
def test_unknowns_placeholders_are_rejected(body):
    text = good_with(
        "Nobody has measured the widget outside the maker's own test setup.", body
    )
    assert check_text(text) == [
        "section `## Unknowns` is empty: say what could not be established"
    ]


def test_cost_section_formats_amounts_and_passes_the_check():
    assert cost_section(0.4312, 2) == "- Spend: $0.4312 (client-estimate)\n- Cap: $2.00"
    assert cost_section(0.5, 1.25) == "- Spend: $0.50 (client-estimate)\n- Cap: $1.25"
    head = fixture("good.md").split("## Cost")[0]
    assert check_text(head + "## Cost\n\n" + cost_section(0.4312, 2)) == []


def test_strip_comments_keeps_the_line_count():
    text = "a\n<!-- one\ntwo\nthree -->\nb <!-- x --> c\n"
    out = strip_comments(text)
    assert out.count("\n") == text.count("\n")
    assert "one" not in out and "x -->" not in out


def test_main_prints_ok_for_a_good_note(capsys):
    path = str(FIXTURES / "good.md")
    assert main([path]) == 0
    assert capsys.readouterr().out == path + ": ok\n"


def test_main_fails_a_bad_note(capsys):
    path = str(FIXTURES / "over-cap.md")
    assert main([path]) == 1
    assert "over the cap" in capsys.readouterr().out


def test_main_fails_a_missing_file(capsys):
    path = str(FIXTURES / "no-such-note.md")
    assert main([path]) == 1
    assert capsys.readouterr().out == path + ": cannot be read\n"


def checked_notes():
    notes = ROOT / "docs" / "research" / "notes"
    return (
        [p for p in sorted(notes.glob("*.md")) if not p.name.startswith("_")]
        if notes.is_dir()
        else []
    )


def test_every_note_in_the_notes_directory_passes():
    for path in checked_notes():
        assert check_text(path.read_text(encoding="utf-8")) == [], path


def test_research_docs_outside_the_notes_directory_are_not_checked():
    names = {p.resolve() for p in checked_notes()}
    for name in ("llm-as-judge.md", "review-judge-calibration.md"):
        assert (ROOT / "docs" / "research" / name).resolve() not in names
