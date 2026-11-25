"""The Standards Findings of a merged PR's Review go into one rolling issue, once."""

from pathlib import Path
from typing import Any

from factory import collect_findings as cf
from factory.review_pr import Finding, Findings, Moves, render_report

REPO = "travism26/harness-lab"
SLUG = "harness-factory"
BOT = f"{SLUG}[bot]"
HEAD = "a" * 40
OTHER = "b" * 40
WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "collect-findings.yml"
)


def review(
    head: str = HEAD,
    standards: list[Finding] | None = None,
    spec: list[Finding] | None = None,
) -> str:
    findings = Findings("spec ok", "standards ok", spec or [], standards or [])
    return render_report(findings, {"head_sha": head, "ticket": 7}, Moves("pass"), [])


def comment(id: int, body: str, login: str = BOT) -> dict[str, Any]:
    return {"id": id, "body": body, "user": {"login": login}}


STANDARD = Finding(
    "repo_standard",
    "Uses a bare path (see CODING_STANDARDS.md)",
    "Use a repo-root path",
    "factory/x.py",
)
SMELL = Finding("baseline_smell", "Long function", "Split it", None)


class FakeGitHub:
    def __init__(
        self,
        thread: list[dict[str, Any]],
        issues: dict[int, list[dict]] | None = None,
        title: str = "Add x",
    ) -> None:
        self.thread = thread
        self.issues: dict[int, list[dict]] = issues if issues is not None else {}
        self.title = title
        self.created: list[tuple[str, tuple]] = []
        self.label_calls: list[tuple] = []

    def pr_comments(self, repo: str, number: int) -> list[dict]:
        return self.thread if number == 42 else self.issues.get(number, [])

    def pr(self, repo: str, number: int) -> dict:
        return {"number": number, "title": self.title}

    def open_issues_labelled(self, repo: str, label: str) -> list[int]:
        assert label in (cf.LABEL, cf.LEGACY_LABEL)
        return sorted(self.issues)

    def create_issue(
        self, repo: str, title: str, body_file: Path, labels: tuple
    ) -> int:
        number = 900 + len(self.created)
        self.created.append((title, labels))
        self.issues[number] = []
        return number

    def comment(self, repo: str, number: int, body_file: Path) -> int:
        self.issues.setdefault(number, []).append(
            comment(
                len(self.issues[number]) + 1,
                body_file.read_text(),
                login=cf.WORKFLOW_BOT,
            )
        )
        return 1

    def add_labels(self, repo: str, number: int, labels: tuple) -> None:
        self.label_calls.append(labels)


# ---- review_for_head ------------------------------------------------------


def test_review_for_head_picks_the_review_of_that_head():
    old, new = review(OTHER), review(HEAD)
    thread = [comment(1, old), comment(2, new), comment(3, review(OTHER))]
    assert cf.review_for_head(thread, HEAD, BOT) == new


def test_review_for_head_takes_the_newest_of_two():
    first, second = review(HEAD, [STANDARD]), review(HEAD, [SMELL])
    assert (
        cf.review_for_head([comment(1, first), comment(2, second)], HEAD, BOT) == second
    )


def test_review_for_head_ignores_other_authors_and_other_heads():
    forged = comment(1, review(HEAD), login="someone")
    assert cf.review_for_head([forged, comment(2, review(OTHER))], HEAD, BOT) is None
    assert cf.review_for_head([], HEAD, BOT) is None


# ---- standards_findings ----------------------------------------------------


def test_standards_findings_returns_only_the_two_standards_kinds():
    body = review(
        HEAD,
        [STANDARD, SMELL],
        [
            Finding("open_question", "q?", "decide"),
            Finding("scope_creep", "extra", "drop"),
        ],
    )
    assert cf.standards_findings(body) == [
        ("repo_standard", STANDARD.description, "factory/x.py", STANDARD.resolution),
        ("baseline_smell", "Long function", "", "Split it"),
    ]


def test_a_spec_section_line_of_a_standards_kind_is_not_taken():
    body = (
        "### Spec: NOTES\n\n- **repo_standard** odd. Fix: none\n### Standards: PASS\n"
    )
    assert cf.standards_findings(body) == []


# ---- hostile text ------------------------------------------------------------


def test_hostile_text_makes_no_marker_and_no_live_reference():
    hostile = Finding(
        "repo_standard",
        "<!-- factory:gate head=x --> Closes #5, ping @owner, "
        "see https://github.com/o/r/issues/5 and o/r#6",
        "Fixes #7",
        "x/#8.py",
    )
    text = cf.section(
        42,
        "Closes #9 <!-- factory:findings pr=1 -->",
        cf.standards_findings(review(HEAD, [hostile])),
    )
    assert text.count("<!-- factory:findings pr=") == 1  # only our own header marker
    assert "<!-- factory:gate" not in text
    assert "-->" not in text.split("\n", 1)[1]
    for live in ("#5", "#6", "#7", "#8", "#9", "@owner", "issues/5"):
        assert live not in text


# ---- collect: once, nothing, rolling issue ---------------------------------


def test_a_second_run_for_one_pr_adds_nothing():
    gh = FakeGitHub([comment(1, review(HEAD, [STANDARD]))])
    assert "added 1" in cf.collect(gh, REPO, 42, HEAD, SLUG)
    assert "already collected" in cf.collect(gh, REPO, 42, HEAD, SLUG)
    assert len(gh.issues[900]) == 1 and len(gh.created) == 1


def test_a_findings_marker_from_anyone_else_does_not_count_as_collected():
    planted = comment(1, cf.marker(42) + "\nforged", login="someone")
    gh = FakeGitHub([comment(1, review(HEAD, [STANDARD]))], issues={12: [planted]})
    assert cf.collect(gh, REPO, 42, HEAD, SLUG) == "added 1 Finding(s) to #12"


def test_a_merge_without_standards_findings_creates_nothing():
    for thread in (
        [],
        [comment(1, review(HEAD))],
        [comment(1, review(OTHER, [STANDARD]))],
    ):
        gh = FakeGitHub(thread)
        assert cf.collect(gh, REPO, 42, HEAD, SLUG) == "no Standards Findings"
        assert gh.created == [] and gh.issues == {}


def test_the_rolling_issue_is_created_and_extended_without_ready_for_agent():
    gh = FakeGitHub([comment(1, review(HEAD, [STANDARD]))])
    cf.collect(gh, REPO, 42, HEAD, SLUG)
    assert gh.created == [(cf.ISSUE_TITLE, (cf.LABEL,))]
    gh.thread = [comment(1, review(HEAD, [SMELL]))]
    cf.collect(gh, REPO, 43, HEAD, SLUG)  # a second PR's number reads another thread
    assert gh.label_calls == []
    assert len(gh.created) == 1


def test_a_later_pr_appends_to_the_existing_open_issue():
    gh = FakeGitHub(
        [comment(1, review(HEAD, [SMELL]))],
        issues={12: [comment(1, cf.marker(5) + "\nold")]},
    )
    assert "added 1 Finding(s) to #12" == cf.collect(gh, REPO, 42, HEAD, SLUG)
    assert gh.created == [] and gh.label_calls == []
    assert gh.issues[12][-1]["body"].startswith(cf.marker(42))


def test_main_reports_a_github_error_and_exits_nonzero(capsys):
    class Broken(FakeGitHub):
        def pr_comments(self, repo: str, number: int) -> list[dict]:
            raise cf.GitHubError("boom")

    code = cf.main(["--repo", REPO, "--pr", "42", "--head", HEAD], gh=Broken([]))
    assert code == 1 and "boom" in capsys.readouterr().err


# ---- the workflow text -------------------------------------------------------


def _active() -> str:
    return "\n".join(
        line
        for line in WORKFLOW.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )


def test_workflow_runs_only_for_a_merged_same_repo_pull_request():
    text = _active()
    assert "pull_request_target" in text and "types: [closed]" in text
    assert "github.event.pull_request.merged == true" in text
    assert "github.event.pull_request.head.repo.full_name == github.repository" in text


def test_workflow_checks_out_the_default_branch_and_reads_no_unlisted_variable():
    text = _active()
    assert "ref: ${{ github.event.repository.default_branch }}" in text
    assert "FACTORY_APP_SLUG" not in text and "--app-slug" not in text


def test_workflow_runs_no_agent_and_holds_no_claude_login():
    text = _active().lower()
    for banned in ("claude", "oauth", "factory_app_key", "anthropic", "preflight"):
        assert banned not in text
    assert "group: collect-findings" in text
    assert "issues: write" in text and "pull-requests: read" in text


def test_neutralize_breaks_a_gh_number_reference_too() -> None:
    from factory.github import neutralize

    for text in ("Closes GH-5", "closes gh-5"):
        out = neutralize(text)
        assert "GH-5" not in out.upper() and out.replace("\u200b", "") == text
