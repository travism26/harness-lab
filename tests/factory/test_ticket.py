import argparse
import json
from pathlib import Path

import pytest

from factory import ticket
from factory.claude import Result
from factory.review_pr import MARKER

REPO = "travism26/harness-lab"


class FakeGitHub:
    def __init__(self, issue=None, pr=None, in_progress=(), comments=()):
        self._issue, self._pr = issue, pr
        self._in_progress, self._comments = list(in_progress), list(comments)
        self.posted, self.added, self.removed = [], [], []

    def issue(self, repo, number):
        return self._issue

    def pr(self, repo, number):
        return self._pr

    def open_issues_labelled(self, repo, label):
        return self._in_progress

    def pr_comments(self, repo, number):
        return self._comments

    def comment(self, repo, number, path):
        self.posted.append((number, path.read_text()))

    def add_labels(self, repo, number, labels):
        self.added += list(labels)

    def remove_labels(self, repo, number, labels):
        self.removed += list(labels)


def _issue(author="travism26", state="OPEN", labels=("ready-for-factory", "project:harness")):
    return {"title": "Add a loop", "body": "Acceptance: it loops", "state": state,
            "author": {"login": author}, "labels": [{"name": n} for n in labels]}


def _root(tmp_path, name="harness", executable=True):
    check = tmp_path / "root" / "projects" / name / "check"
    check.parent.mkdir(parents=True, exist_ok=True)
    check.write_text("#!/usr/bin/env bash\n")
    check.chmod(0o755 if executable else 0o644)


def _args(tmp_path, **kw):
    base = dict(root=str(tmp_path / "root"), repo=REPO, issue=4, pr=9, out=str(tmp_path / "out"), login="subscription",
                app_slug="harness-factory", run_url="https://run", work=str(tmp_path),
                model="sonnet", max_budget_usd=5.0)
    base.update(kw)
    return argparse.Namespace(**base)


def test_claim_labels_the_ticket_and_writes_it(tmp_path):
    _root(tmp_path)
    gh = FakeGitHub(issue=_issue())
    assert ticket.claim(_args(tmp_path), gh) == 0
    assert gh.removed == ["ready-for-factory"] and gh.added == ["in-progress"]
    ctx = json.loads((tmp_path / "out" / "context.json").read_text())
    assert ctx["branch"] == "factory/issue-4" and ctx["pr"] is None
    assert ctx["project"] == "harness" and ctx["bootstrap"] is False
    prompt = ticket.build_prompt(tmp_path / "out")
    assert "projects/harness/check" in prompt and "projects/harness/GLOSSARY.md" in prompt
    assert "not on the base branch yet" not in prompt
    assert "it loops" in (tmp_path / "out" / "ticket.md").read_text()


@pytest.mark.parametrize("labels, executable, match", [
    (("ready-for-factory",), True, "no `project:<name>` label"),
    (("ready-for-factory", "project:harness", "project:other"), True, "more than one"),
    (("ready-for-factory", "project:missing"), True, "no executable `projects/missing/check`"),
    (("ready-for-factory", "project:harness"), False, "no executable `projects/harness/check`"),
])
def test_claim_refuses_a_ticket_without_a_buildable_project(tmp_path, labels, executable, match):
    _root(tmp_path, executable=executable)
    args = _args(tmp_path)
    gh = FakeGitHub(issue=_issue(labels=labels))
    with pytest.raises(ticket.Refused, match=match):
        ticket.claim(args, gh)
    assert gh.added == [] and gh.removed == ["ready-for-factory"]
    assert "did not start" in gh.posted[0][1] and not (tmp_path / "out" / "context.json").exists()


@pytest.mark.parametrize("labels, executable, match", [
    ((), True, "no `project:<name>` label"),
    (("project:harness", "project:other"), True, "more than one"),
    (("project:missing",), True, "no executable `projects/missing/check`"),
    (("project:harness",), False, "no executable `projects/harness/check`"),
])
def test_revise_refuses_a_ticket_without_a_buildable_project(tmp_path, labels, executable, match):
    _root(tmp_path, executable=executable)
    gh = FakeGitHub(issue=_issue(labels=labels), pr=_pr(), comments=[{"body": MARKER}])
    with pytest.raises(RuntimeError, match=match):
        ticket.revise(_args(tmp_path), gh)
    assert "did not start a rework round" in gh.posted[0][1]
    assert not (tmp_path / "out" / "review.md").exists()


def test_revise_refusal_through_the_cli_comments_with_the_run_url(tmp_path, monkeypatch, capsys):
    _root(tmp_path, executable=False)
    gh = FakeGitHub(issue=_issue(labels=("project:harness",)), pr=_pr())
    monkeypatch.setattr(ticket, "GitHub", lambda: gh)
    run = "https://example.test/actions/runs/1"
    code = ticket.main([
        "revise", "--repo", REPO, "--pr", "9", "--out", str(tmp_path / "out"),
        "--login", "subscription", "--app-slug", "harness-factory",
        "--root", str(tmp_path / "root"), "--run-url", run,
    ])
    assert code == 1
    assert len(gh.posted) == 1
    comment = gh.posted[0][1]
    assert gh.posted[0][0] == 4
    assert "did not start a rework round" in comment
    assert "no executable `projects/harness/check`" in comment
    assert run in comment
    assert "AttributeError" not in capsys.readouterr().out
    rework = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "rework.yml").read_text()
    revise = rework.index("python -m factory.ticket revise")
    assert '--run-url "$RUN_URL"' in rework[revise:rework.index("python -m factory.ticket build")]


def test_claim_refuses_a_second_ticket_in_progress(tmp_path):
    _root(tmp_path)
    gh = FakeGitHub(issue=_issue(), in_progress=[2, 4])
    with pytest.raises(ticket.Refused, match="one Ticket at a time: #2"):
        ticket.claim(_args(tmp_path), gh)
    assert gh.added == [] and gh.removed == ["ready-for-factory"]
    assert "did not start" in gh.posted[0][1]


def test_claim_refuses_someone_elses_ticket_on_the_subscription(tmp_path):
    _root(tmp_path)
    gh = FakeGitHub(issue=_issue(author="stranger"))
    with pytest.raises(ticket.Refused, match="switch rule"):
        ticket.claim(_args(tmp_path), gh)


def test_claim_allows_someone_elses_ticket_on_openrouter(tmp_path):
    _root(tmp_path)
    gh = FakeGitHub(issue=_issue(author="stranger"))
    assert ticket.claim(_args(tmp_path, login="openrouter"), gh) == 0


def _pr(labels=("rework", "rework:1"), branch="factory/issue-4"):
    return {"state": "OPEN", "body": "Closes #4", "headRefName": branch,
            "author": {"login": "harness-factory[bot]"},
            "labels": [{"name": n} for n in labels]}


def test_revise_takes_the_latest_factory_review(tmp_path):
    _root(tmp_path)
    comments = [{"body": f"{MARKER}\nold"}, {"body": "human chat"}, {"body": f"{MARKER}\nnew"}]
    gh = FakeGitHub(issue=_issue(), pr=_pr(), comments=comments)
    assert ticket.revise(_args(tmp_path), gh) == 0
    out = tmp_path / "out"
    assert (out / "review.md").read_text().endswith("new")
    ctx = json.loads((out / "context.json").read_text())
    assert ctx["pr"] == 9 and ctx["bootstrap"] is False
    prompt = ticket.build_prompt(out)
    assert "rework round" in prompt and "not on the base branch yet" not in prompt


@pytest.mark.parametrize("pr", [_pr(labels=("rework", "ready-for-human")), _pr(labels=()),
                                _pr(branch="fm/hand-made")])
def test_revise_refuses_prs_not_waiting_for_factory_rework(tmp_path, pr):
    _root(tmp_path)
    gh = FakeGitHub(issue=_issue(), pr=pr, comments=[{"body": MARKER}])
    with pytest.raises(RuntimeError):
        ticket.revise(_args(tmp_path), gh)


def test_build_runs_the_agent_in_the_work_checkout(tmp_path):
    _root(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "ticket.md").write_text("# t\n")
    (out / "context.json").write_text(json.dumps({"project": "harness"}))
    seen = {}

    def agent(prompt, **kw):
        seen.update(kw, prompt=prompt)
        return Result(True, "Added the loop.", "success", 0.5)

    assert ticket.build(_args(tmp_path), run_agent=agent) == 0
    assert seen["may_edit"] and "WebFetch" in seen["disallowed_tools"]
    assert seen["cwd"] == str(tmp_path.resolve())
    assert "rework round" not in seen["prompt"]
    assert "`CLAUDE.md`, `GLOSSARY-MAP.md`" in seen["prompt"]
    assert "`docs/design.md`" not in seen["prompt"]
    assert "`projects/harness/check`" in seen["prompt"]
    assert "`projects/harness/`" in seen["prompt"]
    assert "projects/harness/GLOSSARY.md" in seen["prompt"]
    assert "projects/harness/docs/adr/" in seen["prompt"]
    assert "uv run pytest" not in seen["prompt"]
    assert (out / "summary.md").read_text() == "Added the loop.\n"


def test_pr_body_closes_the_ticket():
    assert ticket.pr_body({"issue": 4}, "Did it.").startswith("Closes #4\n")


def test_release_drops_in_progress(tmp_path):
    gh = FakeGitHub(issue=_issue(labels=("in-progress",)))
    ticket.release(_args(tmp_path), gh)
    assert gh.removed == ["in-progress"] and "failed" in gh.posted[0][1]


def _labels(tmp_path, names):
    path = tmp_path / "root" / "factory" / "labels.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"labels": [
        {"name": f"project:{name}", "color": "c2e0c6", "description": name} for name in names]}))


def test_claim_bootstraps_a_registered_project_with_no_check(tmp_path):
    _labels(tmp_path, ["ai-gateway"])
    gh = FakeGitHub(issue=_issue(labels=("ready-for-factory", "project:ai-gateway")))
    assert ticket.claim(_args(tmp_path), gh) == 0
    ctx = json.loads((tmp_path / "out" / "context.json").read_text())
    assert ctx["project"] == "ai-gateway" and ctx["bootstrap"] is True
    assert gh.removed == ["ready-for-factory"] and gh.added == ["in-progress"]
    prompt = ticket.build_prompt(tmp_path / "out")
    assert "projects/ai-gateway/check" in prompt
    assert "not on the base branch yet" in prompt
    assert "CODING_STANDARDS.md" in prompt and "nothing is published" in prompt
    assert "GLOSSARY-MAP.md" in prompt and "pyproject.toml" in prompt


def test_an_existing_check_stays_an_ordinary_ticket_when_the_name_is_registered(tmp_path):
    _root(tmp_path)
    _labels(tmp_path, ["harness"])
    gh = FakeGitHub(issue=_issue())
    assert ticket.claim(_args(tmp_path), gh) == 0
    ctx = json.loads((tmp_path / "out" / "context.json").read_text())
    assert ctx["project"] == "harness" and ctx["bootstrap"] is False
    prompt = ticket.build_prompt(tmp_path / "out")
    assert "`projects/harness/check`" in prompt and "not on the base branch yet" not in prompt


def test_claim_refuses_an_unregistered_project_with_no_check(tmp_path):
    _labels(tmp_path, ["ai-gateway"])
    gh = FakeGitHub(issue=_issue(labels=("ready-for-factory", "project:other")))
    with pytest.raises(ticket.Refused, match="not registered in `factory/labels.json`"):
        ticket.claim(_args(tmp_path), gh)
    assert gh.added == [] and gh.removed == ["ready-for-factory"]
    assert "did not start" in gh.posted[0][1]
    assert "no executable `projects/other/check`" in gh.posted[0][1]
    assert not (tmp_path / "out" / "context.json").exists()


@pytest.mark.parametrize("slug", ["../x", "a/b", "..", ".", "Bad", "a--b", "-ab"])
def test_claim_refuses_an_unsafe_slug(tmp_path, slug):
    _labels(tmp_path, ["ai-gateway", slug])
    gh = FakeGitHub(issue=_issue(labels=("ready-for-factory", f"project:{slug}")))
    with pytest.raises(ticket.Refused, match="not a safe project name"):
        ticket.claim(_args(tmp_path), gh)
    assert gh.added == [] and "did not start" in gh.posted[0][1]
    assert not (tmp_path / "x").exists()


def test_claim_refuses_an_unsafe_slug_even_when_a_check_file_exists(tmp_path):
    _root(tmp_path, name="Bad")
    _labels(tmp_path, ["Bad"])
    gh = FakeGitHub(issue=_issue(labels=("ready-for-factory", "project:Bad")))
    with pytest.raises(ticket.Refused, match="not a safe project name"):
        ticket.claim(_args(tmp_path), gh)
    assert gh.added == []


def test_a_registered_name_with_a_non_executable_check_is_refused(tmp_path):
    _root(tmp_path, executable=False)
    _labels(tmp_path, ["harness"])
    gh = FakeGitHub(issue=_issue())
    with pytest.raises(ticket.Refused, match="no executable `projects/harness/check`"):
        ticket.claim(_args(tmp_path), gh)
    assert gh.added == [] and "not registered" not in gh.posted[0][1]


def test_revise_bootstraps_when_the_base_has_the_label_and_no_check(tmp_path):
    _labels(tmp_path, ["ai-gateway"])
    gh = FakeGitHub(issue=_issue(labels=("project:ai-gateway",)), pr=_pr(),
                    comments=[{"body": MARKER}])
    assert ticket.revise(_args(tmp_path), gh) == 0
    ctx = json.loads((tmp_path / "out" / "context.json").read_text())
    assert ctx["bootstrap"] is True and ctx["project"] == "ai-gateway" and ctx["pr"] == 9
    prompt = ticket.build_prompt(tmp_path / "out")
    assert "not on the base branch yet" in prompt and "rework round" in prompt


@pytest.mark.parametrize("slug, match", [
    ("other", "not registered in `factory/labels.json`"),
    ("../x", "not a safe project name"),
])
def test_revise_refuses_an_unregistered_or_unsafe_name(tmp_path, slug, match):
    _labels(tmp_path, ["ai-gateway"])
    gh = FakeGitHub(issue=_issue(labels=(f"project:{slug}",)), pr=_pr(), comments=[{"body": MARKER}])
    with pytest.raises(RuntimeError, match=match):
        ticket.revise(_args(tmp_path), gh)
    assert "did not start a rework round" in gh.posted[0][1]
    assert not (tmp_path / "out" / "review.md").exists()


def _wrote(tmp_path, body, mode=0o755, bootstrap=True, project="ai-gateway"):
    out = tmp_path / "out"
    out.mkdir()
    (out / "context.json").write_text(json.dumps({"project": project, "bootstrap": bootstrap}))
    work = tmp_path / "work"
    if body is not None:
        check = work / "projects" / project / "check"
        check.parent.mkdir(parents=True)
        check.write_text(body)
        check.chmod(mode)
    return out, work


def test_verify_does_not_run_the_check_of_an_existing_project(tmp_path):
    out, work = _wrote(tmp_path, "#!/bin/sh\necho ran > ran\nexit 1\n", bootstrap=False,
                       project="harness")
    assert ticket.verify(_args(tmp_path, out=str(out), work=str(work))) == 0
    assert not (work / "ran").exists()


@pytest.mark.parametrize("body, mode", [
    ("#!/bin/sh\nexit 1\n", 0o755),
    ("#!/bin/sh\nexit 0\n", 0o644),
    (None, None),
])
def test_a_failing_or_missing_new_check_blocks_publish(tmp_path, capsys, body, mode):
    out, work = _wrote(tmp_path, body, mode if mode is not None else 0o755)
    code = ticket.main(["verify", "--out", str(out), "--work", str(work)])
    assert code == 1
    assert "nothing is published" in capsys.readouterr().out


def test_a_passing_new_check_lets_publish_proceed(tmp_path, capsys):
    out, work = _wrote(tmp_path, "#!/bin/sh\necho ran > ran\nexit 0\n")
    assert ticket.main(["verify", "--out", str(out), "--work", str(work)]) == 0
    assert (work / "ran").is_file()
    assert "Bootstrap check passed" in capsys.readouterr().out


def test_the_new_check_does_not_see_factory_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "gh-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "actions-secret")
    monkeypatch.setenv("FACTORY_SUBSCRIPTION_TOKEN", "sub-secret")
    monkeypatch.setenv("FACTORY_OPENROUTER_KEY", "or-secret")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-secret")
    monkeypatch.setenv("FACTORY_SENTINEL", "kept")
    script = (
        "#!/bin/sh\n"
        "printf 'GH=%s\\nGITHUB=%s\\nSUB=%s\\nOR=%s\\nOAUTH=%s\\nSENTINEL=%s\\n' "
        "\"$GH_TOKEN\" \"$GITHUB_TOKEN\" \"$FACTORY_SUBSCRIPTION_TOKEN\" "
        "\"$FACTORY_OPENROUTER_KEY\" \"$CLAUDE_CODE_OAUTH_TOKEN\" \"$FACTORY_SENTINEL\" > seen\n"
    )
    out, work = _wrote(tmp_path, script)
    assert ticket.verify(_args(tmp_path, out=str(out), work=str(work))) == 0
    seen = (work / "seen").read_text()
    assert seen == "GH=\nGITHUB=\nSUB=\nOR=\nOAUTH=\nSENTINEL=kept\n"
    for secret in ("gh-secret", "actions-secret", "sub-secret", "or-secret", "oauth-secret"):
        assert secret not in seen


def test_workflows_run_the_new_check_before_publish_without_secrets():
    root = Path(__file__).resolve().parents[2]
    for name in ("implement.yml", "rework.yml"):
        text = (root / ".github" / "workflows" / name).read_text()
        build = text.index("python -m factory.ticket build")
        go = text.index("- name: Install Go for the new Project")
        step = text.index("- name: Run the new Project check")
        verify = text.index("python -m factory.ticket verify")
        publish = text.index("python -m factory.ticket publish")
        assert build < go < step < verify < publish
        go_step = text[go:step]
        assert "steps.project.outputs.bootstrap == 'true'" in go_step
        assert "hashFiles(format('work/projects/{0}/go.mod', steps.project.outputs.name))" in go_step
        assert "actions/setup-go@v7.0.0" in go_step
        assert "go-version-file: work/projects/${{ steps.project.outputs.name }}/go.mod" in go_step
        assert "cache-dependency-path: work/projects/${{ steps.project.outputs.name }}/go.sum" in go_step
        check_step = text[step:verify]
        assert "steps.project.outputs.bootstrap == 'true'" in check_step
        assert "secrets." not in check_step and "preflight.outputs.token" not in check_step
        assert 'GH_TOKEN: ""' in check_step and 'GITHUB_TOKEN: ""' in check_step
    implement = (root / ".github" / "workflows" / "implement.yml").read_text()
    assert "if: failure() && steps.claim.outcome == 'success'" in implement
