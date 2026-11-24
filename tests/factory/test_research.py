"""The research steps (`factory/research.py`), tested with fakes: no model, no network, no GitHub."""

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from factory import claude, metrics, research, research_note, run_record, ticket
from factory.claude import Result
from factory.record import WORKFLOWS
from factory.sync_labels import load_labels
from tests.factory.support import (
    BOT,
    REPO,
    RUN_URL,
    SLUG,
    bot_comment,
    marker_of,
    step_args,
)
from tests.factory.support import (
    FakeGitHub as RecordGitHub,
)

ROOT = Path(__file__).resolve().parents[2]
GOOD = (ROOT / "tests/factory/fixtures/research/good.md").read_text()
WORKFLOW = ROOT / ".github/workflows/research.yml"
# Built at test time so no file holds a credential-shaped literal.
SECRET = "ghp_" + "a" * 36


def request(
    question="Does the widget work?",
    scope="Its price and speed.",
    starts="",
    cap="",
    out_of_scope="Nothing else.",
):
    return (
        f"## Question\n\n{question}\n\n## Scope\n\n{scope}\n\n"
        f"## Public starting points\n\n{starts}\n\n## Cost cap (USD)\n\n{cap}\n\n"
        f"## Out of scope\n\n{out_of_scope}\n"
    )


class FakeGitHub:
    def __init__(
        self,
        body=None,
        state="OPEN",
        author="travism26",
        labels=("ready-for-research",),
        in_progress=(),
        title="Widget research",
    ):
        self.data = {
            "title": title,
            "body": request() if body is None else body,
            "state": state,
            "author": {"login": author},
        }
        self.labels = list(labels)
        self.in_progress = list(in_progress)
        self.posted, self.added, self.removed, self.prs = [], [], [], []

    def issue(self, repo, number):
        return dict(self.data, labels=[{"name": n} for n in self.labels])

    def open_issues_labelled(self, repo, label):
        return self.in_progress

    def comment(self, repo, number, path):
        self.posted.append((number, path.read_text()))

    def add_labels(self, repo, number, labels):
        self.added += list(labels)
        self.labels += list(labels)

    def remove_labels(self, repo, number, labels):
        self.removed += list(labels)
        self.labels = [n for n in self.labels if n not in labels]

    def bot_user_id(self, slug):
        return 42

    def create_draft_pr(self, repo, base, head, title, body_file):
        self.prs.append((base, head, title, body_file.read_text()))
        return f"https://github.com/{REPO}/pull/9"

    def pr(self, repo, number):
        return {}

    def pr_comments(self, repo, number):
        return []

    def update_comment(self, repo, comment_id, path):
        pass


def args(tmp_path, **kw):
    base = {
        "repo": REPO,
        "issue": 4,
        "out": str(tmp_path / "out"),
        "login": "subscription",
        "app_slug": SLUG,
        "run_url": "https://run",
        "work": str(tmp_path / "work"),
        "model": "sonnet",
        "max_budget_usd": 2.0,
    }
    base.update(kw)
    return argparse.Namespace(**base)


# ---- the tools -------------------------------------------------------------


def test_the_agent_gets_the_read_tools_and_the_web_and_nothing_that_writes(tmp_path):
    assert research.ALLOWED_TOOLS == ["Read", "Grep", "Glob", "WebFetch", "WebSearch"]
    for tool in (
        "Bash",
        "Edit",
        "Write",
        "NotebookEdit",
        "Agent",
        "Task",
        "Read(//proc/**)",
    ):
        assert tool in research.DENIED_TOOLS
    assert (
        "WebFetch" not in research.DENIED_TOOLS
        and "WebSearch" not in research.DENIED_TOOLS
    )
    seen = {}

    def agent(text, **kw):
        seen.update(kw)
        return Result(True, "# n\n", "success", 0.1, {})

    out = tmp_path / "out"
    out.mkdir()
    (out / "request.md").write_text("# t\n")
    research.answer(args(tmp_path), run_agent=agent)
    assert seen["allowed_tools"] == research.ALLOWED_TOOLS
    assert seen["disallowed_tools"] == research.DENIED_TOOLS
    assert "may_edit" not in seen


def test_the_agent_command_has_no_permission_mode_and_denies_the_shell():
    cmd = claude.command(
        "sonnet", 2, research.ALLOWED_TOOLS, research.DENIED_TOOLS, may_edit=False
    )
    assert "--permission-mode" not in cmd
    assert "Bash" in cmd[cmd.index("--disallowedTools") + 1]


# ---- the request -----------------------------------------------------------


def refused(body, knob=2.0):
    with pytest.raises(research.Refused) as raised:
        research.request_budget(body, knob)
    return str(raised.value)


def test_a_valid_request_with_no_cap_gets_the_knob():
    assert research.request_budget(request(), 2.0) == 2.0


@pytest.mark.parametrize(
    "cap, value",
    [("1.50", 1.5), ("$1.50", 1.5), ("$ 1.5", 1.5), ("2", 2.0), ("2.00", 2.0)],
)
def test_a_cap_up_to_the_knob_is_the_runs_cap(cap, value):
    assert research.request_budget(request(cap=cap), 2.0) == value


def test_a_cap_above_the_knob_is_refused():
    assert "can lower the cap, not raise it" in refused(request(cap="3"))


@pytest.mark.parametrize(
    "cap, message",
    [
        ("0", "above zero"),
        ("0.00", "above zero"),
        ("abc", "not a dollar amount"),
        ("-1", "not a dollar amount"),
    ],
)
def test_a_cap_that_is_not_a_positive_amount_is_refused(cap, message):
    assert message in refused(request(cap=cap))


@pytest.mark.parametrize("heading", research.REQUEST_HEADINGS)
def test_each_missing_heading_is_refused(heading):
    body = request().replace(f"## {heading}\n", "")
    assert f"missing `## {heading}`" in refused(body)


def test_a_repeated_heading_is_refused():
    assert "`## Scope` more than once" in refused(request() + "\n## Scope\n\nagain\n")


@pytest.mark.parametrize(
    "field, heading",
    [("question", "Question"), ("scope", "Scope"), ("out_of_scope", "Out of scope")],
)
def test_an_empty_required_section_is_refused(field, heading):
    assert f"the request's `## {heading}` is empty" in refused(request(**{field: ""}))
    # A comment alone is empty too.
    assert f"`## {heading}` is empty" in refused(request(**{field: "<!-- fill in -->"}))


def test_a_starting_point_must_be_https():
    assert "is not `https://`" in refused(request(starts="http://example.com/a"))
    assert "is not `https://`" in refused(request(starts="FTP://example.com/a"))
    assert research.request_budget(request(starts="https://example.com/a"), 2.0) == 2.0


def test_a_credential_shaped_string_is_refused():
    assert "credential-shaped" in refused(request(scope="use " + SECRET))


def test_the_issue_template_holds_the_five_headings_once_in_order():
    text = (ROOT / ".github/ISSUE_TEMPLATE/research-request.md").read_text()
    names = [s.heading for s in research_note.sections(text)]
    assert names == list(research.REQUEST_HEADINGS)


def test_the_unfilled_template_is_refused():
    text = (ROOT / ".github/ISSUE_TEMPLATE/research-request.md").read_text()
    body = text.split("---\n", 2)[2]
    assert "`## Question` is empty" in refused(body)


def test_the_note_template_holds_the_required_headings_once_in_order():
    text = (ROOT / "docs/research/notes/_template.md").read_text()
    assert [s.heading for s in research_note.sections(text)] == list(
        research_note.REQUIRED
    )


# ---- claim -----------------------------------------------------------------


def test_claim_starts_the_request(tmp_path):
    gh = FakeGitHub()
    assert research.claim(args(tmp_path, max_budget_usd=3.0), gh) == 0
    assert gh.removed == ["ready-for-research"] and gh.added == ["in-progress"]
    ((number, body),) = gh.posted
    assert number == 4 and body.startswith(research.STARTED_PREFIX)
    assert not body.startswith(ticket.STARTED_PREFIX)
    out = tmp_path / "out"
    assert "Does the widget work?" in (out / "request.md").read_text()
    ctx = json.loads((out / "context.json").read_text())
    assert ctx["branch"] == "research/issue-4" and ctx["budget"] == 3.0
    assert (
        ctx["repo"] == REPO and ctx["issue"] == 4 and ctx["title"] == "Widget research"
    )


def test_claim_takes_the_requests_lower_cap(tmp_path):
    research.claim(args(tmp_path), FakeGitHub(body=request(cap="1.25")))
    assert json.loads((tmp_path / "out" / "context.json").read_text())["budget"] == 1.25


@pytest.mark.parametrize(
    "gh, reason",
    [
        (FakeGitHub(state="CLOSED"), "the Ticket is closed"),
        (
            FakeGitHub(in_progress=[7]),
            "one Ticket at a time: #7 is still `in-progress`",
        ),
        (FakeGitHub(author="stranger"), "switch rule"),
        (FakeGitHub(body=request(question="")), "the request's `## Question` is empty"),
    ],
)
def test_claim_refuses_and_says_why(tmp_path, gh, reason):
    with pytest.raises(research.Refused) as raised:
        research.claim(args(tmp_path), gh)
    assert reason in str(raised.value)
    ((_number, body),) = gh.posted
    assert body.startswith("The factory did not start this research request: ")
    assert reason in body and "`ready-for-research` has been removed" in body
    assert gh.removed == ["ready-for-research"] and gh.added == []


def test_a_research_claim_is_not_a_build_ticket_to_the_metrics():
    comment = bot_comment(1, f"{research.STARTED_PREFIX} [Run](https://run)\n", BOT)
    comment["issue_url"] = f"https://api.github.com/repos/{REPO}/issues/4"
    assert metrics.claimed_issues([comment], SLUG) == []
    assert metrics.tickets_from([{"workflow": "research", "issue": 4}]) == []


# ---- answer ----------------------------------------------------------------


def answered(tmp_path, result, request_text="# Widgets\n\nWhat is the widget?\n"):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    (out / "request.md").write_text(request_text)
    seen = []

    def agent(text, **kw):
        seen.append(text)
        return result

    return out, seen, agent


def test_answer_writes_the_reply_and_only_the_numbers(tmp_path, capsys):
    message = {
        "subtype": "success",
        "total_cost_usd": 0.4,
        "result": "SECRET MODEL WORDS",
    }
    out, seen, agent = answered(
        tmp_path, Result(True, "  # Note\n\nbody\n\n", "success", 0.4, message)
    )
    assert research.answer(args(tmp_path), run_agent=agent) == 0
    assert (out / "reply.md").read_text() == "# Note\n\nbody\n"
    saved = (out / "result.json").read_text()
    assert (
        json.loads(saved)["total_cost_usd"] == 0.4 and "SECRET MODEL WORDS" not in saved
    )
    assert "The agent finished: $0.40" in capsys.readouterr().out
    prompt = seen[0]
    assert (
        f"{research.REQUEST_OPEN}\n# Widgets\n\nWhat is the widget?\n{research.REQUEST_CLOSE}"
        in prompt
    )
    assert "$2" in prompt


def test_answer_raises_the_budget_message_on_a_budget_stop(tmp_path):
    out, _, agent = answered(
        tmp_path, Result(False, "x", "error_max_budget_usd", 2.0, {})
    )
    with pytest.raises(
        RuntimeError, match="stopped at its budget cap.*FACTORY_RESEARCH_BUDGET_USD"
    ):
        research.answer(args(tmp_path), run_agent=agent)
    assert not (out / "reply.md").exists()


# ---- note_from_reply and compose ---------------------------------------------


def test_a_preamble_before_the_title_is_dropped():
    assert (
        research.note_from_reply("Here is the note:\n\n# T\n\n## Question\n\nq\n")
        == "# T\n\n## Question\n\nq"
    )


def test_a_wrapping_code_fence_is_dropped():
    assert research.note_from_reply("```markdown\n# T\n\nbody\n```\n") == "# T\n\nbody"


def test_a_reply_with_no_heading_is_kept_as_it_is():
    assert research.note_from_reply("  just words\n") == "just words"


def test_compose_replaces_a_model_written_cost_section():
    reply = GOOD.replace(
        "- Spend: $0.42 (client-estimate)", "- Spend: $0.01 (client-estimate)"
    )
    note = research.compose(reply, 0.42, 2)
    assert note.count("## Cost") == 1 and "$0.01" not in note
    assert note.endswith("## Cost\n\n- Spend: $0.42 (client-estimate)\n- Cap: $2.00\n")


def test_compose_removes_a_cost_section_in_the_middle():
    reply = (
        "# T\n\n## Question\n\nq\n\n## Cost\n\nit was free\n\n## Findings\n\nf\n\n"
        "## Sources\n\n- [vendor] https://a.example/x: y\n\n## Unknowns\n\nu\n"
    )
    note = research.compose(reply, 0.5, 1)
    assert "it was free" not in note and note.count("## Cost") == 1
    assert "## Findings\n\nf\n" in note and note.index("## Unknowns") < note.index(
        "## Cost"
    )
    assert research_note.check_text(note) == []


def test_a_composed_good_note_passes_the_check():
    assert research_note.check_text(research.compose(GOOD, 0.42, 2)) == []
    wrapped = "Sure.\n\n```markdown\n" + GOOD + "\n```\n"
    assert research_note.check_text(research.compose(wrapped, 0.42, 2)) == []


# ---- check -----------------------------------------------------------------


def check_out(tmp_path, reply=GOOD, numbers=None):
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    if reply is not None:
        (out / "reply.md").write_text(reply)
    if numbers is not None:
        (out / "result.json").write_text(json.dumps(numbers))
    return out


def test_check_passes_a_good_reply_and_writes_the_note(tmp_path, capsys):
    out = check_out(tmp_path, numbers={"total_cost_usd": 0.42})
    assert research.check(args(tmp_path)) == 0
    assert research_note.check_text((out / "note.md").read_text()) == []
    assert "The note passed its check" in capsys.readouterr().out
    assert not (out / "check-failed.md").exists()


def test_check_fails_a_note_over_its_cap(tmp_path):
    out = check_out(tmp_path, numbers={"total_cost_usd": 2.5})
    with pytest.raises(RuntimeError, match="the note failed its check"):
        research.check(args(tmp_path))
    assert "over the cap" in (out / "check-failed.md").read_text()


def test_check_fails_a_reply_with_no_sources(tmp_path):
    reply = (ROOT / "tests/factory/fixtures/research/missing-sources.md").read_text()
    out = check_out(tmp_path, reply=reply, numbers={"total_cost_usd": 0.1})
    with pytest.raises(RuntimeError, match="failed its check"):
        research.check(args(tmp_path))
    assert "## Sources" in (out / "check-failed.md").read_text()


@pytest.mark.parametrize(
    "numbers",
    [
        None,
        {},
        {"total_cost_usd": "0.4"},
        {"total_cost_usd": True},
        {"total_cost_usd": -0.1},
        {"total_cost_usd": None},
    ],
)
def test_check_fails_without_a_usable_spend_figure(tmp_path, numbers):
    out = check_out(tmp_path, numbers=numbers)
    with pytest.raises(RuntimeError, match="no spend figure"):
        research.check(args(tmp_path))
    assert "no spend figure" in (out / "check-failed.md").read_text()
    assert not (out / "note.md").exists()


def test_check_raises_when_there_is_no_reply(tmp_path):
    check_out(tmp_path, reply=None, numbers={"total_cost_usd": 0.1})
    with pytest.raises(RuntimeError, match="left no reply"):
        research.check(args(tmp_path))


# ---- publish ---------------------------------------------------------------


def git(path, *a):
    return subprocess.run(
        ["git", *a], cwd=path, capture_output=True, text=True, check=True
    ).stdout


def work_checkout(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    (work / "README.md").write_text("hi\n")
    git(work, "add", "-A")
    git(
        work,
        "-c",
        "user.name=T",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-q",
        "-m",
        "init",
    )
    return work


def publish_out(tmp_path, note=None):
    out = tmp_path / "out"
    out.mkdir()
    (out / "note.md").write_text(
        research.compose(GOOD, 0.42, 2) if note is None else note
    )
    return out


def test_publish_commits_only_the_note_and_opens_a_draft_pr(
    tmp_path, monkeypatch, capsys
):
    work = work_checkout(tmp_path)
    (work / "stray.txt").write_text("not for the commit\n")
    out = publish_out(tmp_path)
    pushed = []

    def fake_git(path, *a):
        if a[0] == "push":
            pushed.append(a)
            return ""
        return ticket._git(path, *a)

    monkeypatch.setattr(research, "_git", fake_git)
    monkeypatch.setenv("GH_TOKEN", "tok")
    gh = FakeGitHub(labels=("in-progress",))
    assert research.publish(args(tmp_path), gh) == 0
    assert git(work, "show", "--name-only", "--format=", "HEAD").split() == [
        "docs/research/notes/issue-4.md"
    ]
    assert git(work, "show", "-s", "--format=%an <%ae>|%s", "HEAD").strip() == (
        f"{SLUG}[bot] <42+{SLUG}[bot]@users.noreply.github.com>|"
        "research: Widget research (note, #4)"
    )
    assert (work / "stray.txt").exists() and "stray.txt" not in git(work, "ls-files")
    assert pushed[0][-1] == "HEAD:refs/heads/research/issue-4"
    ((base, head, title, body),) = gh.prs
    assert (base, head, title) == (
        "main",
        "research/issue-4",
        "Research note: Widget research",
    )
    assert body.startswith("Closes #4\n")
    assert "Does the widget do" not in body and "example.com" not in body
    ((number, comment),) = gh.posted
    assert number == 4 and comment.startswith(ticket.OPENED_PREFIX)
    assert gh.removed == ["in-progress"]
    assert "Opened https://github.com/" in capsys.readouterr().out
    assert (out / "pr-body.md").read_text() == body


def test_publish_refuses_a_note_that_fails_its_check_before_any_git_or_github_call(
    tmp_path, monkeypatch
):
    publish_out(tmp_path, note=GOOD.replace("$0.42", "$9.00"))
    monkeypatch.setattr(research, "_git", lambda *a: pytest.fail("git was called"))
    gh = FakeGitHub()
    gh.issue = lambda *a: pytest.fail("GitHub was called")
    with pytest.raises(RuntimeError, match="failed its check"):
        research.publish(args(tmp_path), gh)


def test_publish_without_a_note_raises(tmp_path):
    (tmp_path / "out").mkdir()
    with pytest.raises(RuntimeError, match="no note"):
        research.publish(args(tmp_path), FakeGitHub())


def test_publish_with_the_note_already_on_the_base_branch_raises(tmp_path, monkeypatch):
    work = work_checkout(tmp_path)
    publish_out(tmp_path)
    dest = work / "docs/research/notes/issue-4.md"
    dest.parent.mkdir(parents=True)
    dest.write_text((tmp_path / "out" / "note.md").read_text())
    git(work, "add", "-A")
    git(
        work,
        "-c",
        "user.name=T",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-q",
        "-m",
        "note",
    )
    monkeypatch.setenv("GH_TOKEN", "tok")
    with pytest.raises(RuntimeError, match="nothing to publish"):
        research.publish(args(tmp_path), FakeGitHub())


# ---- release ---------------------------------------------------------------


def test_release_says_so_and_drops_in_progress(tmp_path):
    gh = FakeGitHub(labels=("in-progress",))
    assert research.release(args(tmp_path, run_url=RUN_URL), gh) == 0
    ((_number, body),) = gh.posted
    assert (
        body.startswith(ticket.failed_prefix(RUN_URL))
        and "`ready-for-research`" in body
    )
    assert "no pull request was opened" not in body
    assert gh.removed == ["in-progress"]


def test_release_lists_the_checks_problems_and_defuses_a_comment_closer(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "check-failed.md").write_text(
        "- section `## Sources` lists nothing\n- a --> b <!-- c\n"
    )
    gh = FakeGitHub(labels=("in-progress",))
    research.release(args(tmp_path), gh)
    body = gh.posted[0][1]
    assert "The note failed its check, so no pull request was opened:" in body
    assert "section `## Sources` lists nothing" in body
    assert "-->" not in body and "<!--" not in body


# ---- the Run record ----------------------------------------------------------

OPENED = f"{ticket.OPENED_PREFIX}https://github.com/{REPO}/pull/9\n"
FAILED = (
    f"{ticket.failed_prefix(RUN_URL)}. `in-progress` has been removed; "
    "re-apply `ready-for-research` to try again.\n"
)


def test_an_opened_research_run_leaves_a_research_record(tmp_path):
    gh = RecordGitHub(comments=[bot_comment(1, OPENED)])
    run_record.write(step_args("research", tmp_path), gh)
    record = marker_of(gh.thread[0]["body"])
    assert record["workflow"] == "research" and record["outcome"] == "ok"
    assert record["pr"] == 9 and record["issue"] == 4


def test_a_note_that_failed_its_check_is_a_check_failed_record(tmp_path):
    gh = RecordGitHub(comments=[bot_comment(1, FAILED)])
    run_record.write(
        step_args(
            "research",
            tmp_path,
            agent_outcome="success",
            verify_outcome="failure",
            publish_outcome="skipped",
            job_status="failure",
        ),
        gh,
    )
    record = marker_of(gh.thread[0]["body"])
    assert record["outcome"] == "fail" and record["reason"] == "check-failed"
    assert record["workflow"] == "research"


def test_an_agent_that_hit_its_budget_leaves_that_reason(tmp_path):
    (tmp_path / "result.json").write_text(
        json.dumps({"subtype": "error_max_budget_usd"})
    )
    gh = RecordGitHub(comments=[bot_comment(1, FAILED)])
    run_record.write(
        step_args(
            "research",
            tmp_path,
            agent_outcome="failure",
            publish_outcome="skipped",
            job_status="failure",
        ),
        gh,
    )
    assert marker_of(gh.thread[0]["body"])["reason"] == "error_max_budget_usd"


def test_backfill_still_walks_only_the_three_old_workflows():
    assert WORKFLOWS == ("implement", "rework", "review")


# ---- the workflow ------------------------------------------------------------


def jobs():
    text = WORKFLOW.read_text()
    claim = text.split("\n  claim:\n")[1].split("\n  research:\n")[0]
    agent, publish = text.split("\n  research:\n")[1].split("\n  publish:\n")
    return text, claim, agent, publish


def test_only_the_owners_label_on_an_issue_starts_the_workflow():
    text, _, _, _ = jobs()
    for clause in (
        "github.event.label.name == 'ready-for-research'",
        "github.event.sender.login == github.repository_owner",
        "!github.event.issue.pull_request",
    ):
        assert text.count(clause) == 2
    assert "'factory-ticket'" in text.split("concurrency:")[1].split("env:")[0]


def test_the_agent_job_holds_no_github_token_and_no_app():
    _, _, agent, _ = jobs()
    assert "factory.research answer" in agent
    for banned in (
        "FACTORY_APP_KEY",
        "create-github-app-token",
        "factory-preflight",
        "GH_TOKEN",
        "steps.preflight",
        "steps.app",
        "github.token",
    ):
        assert banned not in agent


def test_the_token_jobs_run_no_agent_and_hold_no_login():
    _, claim, _, publish = jobs()
    for job in (claim, publish):
        for banned in (
            "factory.research answer",
            "@anthropic-ai/claude-code",
            "FACTORY_SUBSCRIPTION_TOKEN",
            "FACTORY_OPENROUTER_KEY",
        ):
            assert banned not in job


def test_publish_checks_the_note_with_no_token_before_it_publishes():
    _, _, _, publish = jobs()
    assert publish.index("factory.research check") < publish.index(
        "factory.research publish"
    )
    step = publish.split("- name: Check the note")[1].split("- name:")[0]
    assert 'GH_TOKEN: ""' in step and "steps.app.outputs.token" not in step


def test_the_workflow_leaves_a_research_run_record_with_the_budget_knob():
    text = WORKFLOW.read_text()
    assert "python -m factory.run_record write --workflow research" in text
    assert "vars.FACTORY_RESEARCH_BUDGET_USD || '2'" in text


def test_the_start_label_is_registered_as_owner_applied():
    rows = [label for label in load_labels() if label.name == "ready-for-research"]
    assert len(rows) == 1 and rows[0].description.startswith("Owner-applied")
