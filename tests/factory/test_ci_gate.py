"""Decision tests for a CI result on a factory draft (factory/ci_gate.py)."""

import json

import pytest

from factory.ci_gate import (
    Decision, FailedJob, bound_excerpt, conclusion_for_trigger, decide, failed_findings,
    inputs_ready, wait_for_inputs,
)
from factory.github import GitHubError, select_head_run
from factory.review_pr import MARKER, gate_line
from factory import ci_gate

REPO = "travism26/harness-lab"
SHA = "ba2ea98635fd261912159e8bc8f4f54f1f5411d0"
RUN = 43078560378
TOKEN = "ghp_" + "b" * 20
EXCERPT = "--- FAIL: TestOnlyPostMessages (5.00s)\n" + TOKEN


def _pass(head=SHA, number=1):
    body = "\n".join([MARKER, gate_line(head, False, "review"),
                      "## Factory review: PASS", "", "Spec passed."])
    return {"id": number, "body": body}


def _charge(head=SHA, number=1, source="review", add=("rework", "rework:1"), nonce="aa",
            ci_run=None):
    body = "\n".join([
        MARKER,
        gate_line(head, True, source, ci_run=ci_run, nonce=nonce, add=add),
        "## Factory review: BLOCKED", "", "blocked",
    ])
    return {"id": number, "body": body}


def event(**kw):
    base = dict(
        conclusion="failure", event="pull_request", head_branch="factory/issue-114",
        head_sha=SHA, head_repo=REPO, repo=REPO, run_id=RUN,
        run_url=f"https://github.com/{REPO}/actions/runs/{RUN}",
        pr=118, pr_state="OPEN", pr_draft=True, pr_author="travism26-factory[bot]",
        pr_head_repo=REPO, pr_head_sha=SHA, labels=(), body="Closes #114\n",
        comments=(_pass(),),
        failed_jobs=(FailedJob("check ai-gateway", EXCERPT),),
        app_slug="travism26-factory",
        issue_labels=("in-progress", "project:ai-gateway"),
    )
    base.update(kw)
    return ci_gate.GateEvent(**base)


def test_ci_failure_after_a_pass_becomes_the_rework_finding():
    decision = decide(event(), nonce="abc")
    assert decision.action == "rework"
    assert decision.add == ("rework", "rework:1")
    assert decision.remove == ()
    assert "check ai-gateway" in decision.comment
    assert "TestOnlyPostMessages" in decision.comment
    assert TOKEN not in decision.comment and "ghp_" not in decision.comment
    assert "[REDACTED]" in decision.comment
    assert "<!-- factory:review -->" in decision.comment
    assert f"ci-run={RUN}" in decision.comment
    assert "charged=1" in decision.comment and "nonce=abc" in decision.comment
    assert "Sent to rework: round 1 of 2" in decision.comment
    assert "### Spec: BLOCKER" in decision.comment


def test_the_third_blocker_hands_the_pr_to_a_human():
    decision = decide(event(labels=("rework", "rework:2")), nonce="abc")
    assert decision.action == "human"
    assert decision.add == ("ready-for-human",)
    assert decision.remove == ("rework",)
    assert "check ai-gateway" in decision.comment
    assert "ready-for-human" in decision.comment
    assert "TestOnlyPostMessages" in decision.comment


def test_a_second_new_head_is_round_two():
    decision = decide(event(labels=("rework", "rework:1")), nonce="abc")
    assert decision.action == "rework"
    assert decision.add == ("rework", "rework:2")
    assert "rework:1" in decision.remove and "rework" in decision.remove
    assert "round 2 of 2" in decision.comment


def test_ci_and_review_on_the_same_head_are_one_round():
    charged = _charge(add=("rework", "rework:1"))
    decision = decide(event(labels=("rework", "rework:1"), comments=(charged,), run_id=RUN + 1),
                      nonce="new")
    assert decision.action == "join"
    assert decision.add == () and decision.remove == ()
    assert "counter stays" in decision.comment
    assert "Sent to rework:" not in decision.comment
    assert "check ai-gateway" in decision.comment
    assert "charged=0" in decision.comment


def test_same_head_already_at_the_cap_does_not_escalate():
    charged = _charge(add=("rework", "rework:2"), nonce="aa01")
    decision = decide(event(labels=("rework", "rework:2"), comments=(charged,), run_id=RUN + 1))
    assert decision.action == "join"
    assert "ready-for-human" not in decision.add


@pytest.mark.parametrize("branch", [
    "main", "feature/x", "factory/issue-", "factory/issue-114-extra", "factory/other",
])
def test_a_non_factory_branch_is_ignored(branch):
    assert decide(event(head_branch=branch)).action == "ignore"


def test_a_fork_workflow_run_is_ignored():
    assert decide(event(head_repo="stranger/harness-lab")).action == "ignore"


def test_a_fork_pull_request_is_ignored():
    assert decide(event(pr_head_repo="stranger/harness-lab")).action == "ignore"


def test_an_owner_authored_pull_request_is_ignored():
    assert decide(event(pr_author="travism26")).action == "ignore"


def test_a_pull_request_that_is_not_a_draft_is_not_reworked():
    assert decide(event(pr_draft=False)).action == "ignore"


def test_a_push_and_a_cancelled_run_are_ignored():
    assert decide(event(event="push", head_branch="main")).action == "ignore"
    assert decide(event(conclusion="cancelled")).action == "ignore"


def test_a_stale_head_is_ignored():
    other = "f" * 40
    assert decide(event(pr_head_sha=other)).action == "ignore"


def test_a_branch_that_closes_a_different_ticket_is_ignored():
    assert decide(event(body="Closes #7\n")).action == "ignore"


def test_duplicate_event_does_not_open_another_round():
    comment = _charge(source="ci", ci_run=RUN, nonce="abc", add=("rework", "rework:1"))
    decision = decide(event(labels=("rework", "rework:1"), comments=(_pass(), comment)))
    assert decision == Decision("ignore", "duplicate ci run")


def test_duplicate_event_finishes_labels_when_the_comment_landed_first():
    comment = _charge(source="ci", ci_run=RUN, nonce="abc", add=("rework", "rework:1"))
    decision = decide(event(labels=(), comments=(_pass(), comment)))
    assert decision.action == "finish"
    assert decision.comment == ""
    assert decision.add == ("rework", "rework:1")
    assert decision.remove == ()


def test_duplicate_human_charge_finishes_without_a_second_comment():
    comment = _charge(source="ci", ci_run=RUN, nonce="abc", add=("ready-for-human",))
    decision = decide(event(labels=("rework", "rework:2"), comments=(comment,)))
    assert decision.action == "finish"
    assert decision.add == ("ready-for-human",)
    assert decision.remove == ("rework",)
    assert decision.comment == ""


def test_ci_green_then_review_pass_clears_in_progress():
    ci_run = {"conclusion": "success", "databaseId": 99, "url": "https://example.test/ci"}
    assert conclusion_for_trigger("Review", "success", ci_run) == "success"
    assert conclusion_for_trigger("Review", "success", {"conclusion": "failure"}) == "ignored"
    assert conclusion_for_trigger("Review", "failure", None) == "ignored"
    assert conclusion_for_trigger("CI", "failure", None) == "failure"
    decision = decide(event(conclusion="success", failed_jobs=(), run_id=99,
                            run_url="https://example.test/ci", comments=(_pass(),)))
    assert decision.action == "settle" and decision.clear_in_progress and decision.issue == 114
    ignored = decide(event(conclusion="ignored", failed_jobs=()))
    assert ignored.action == "ignore"


def test_green_ci_after_pass_clears_in_progress():
    decision = decide(event(conclusion="success", failed_jobs=()))
    assert decision.action == "settle"
    assert decision.clear_in_progress and decision.issue == 114
    assert decision.comment == ""
    assert decision.add == () and decision.remove == ()


def test_green_ci_on_a_ready_pull_request_still_clears_in_progress():
    decision = decide(event(conclusion="success", failed_jobs=(), pr_draft=False))
    assert decision.action == "settle" and decision.clear_in_progress


def test_a_green_rerun_leaves_an_open_rework_round_alone():
    charged = _charge()
    decision = decide(event(conclusion="success", failed_jobs=(),
                            labels=("rework", "rework:1"), comments=(_pass(), charged)))
    assert decision.action == "ignore"


def test_green_ci_without_a_passing_review_leaves_in_progress():
    assert decide(event(conclusion="success", failed_jobs=(), comments=())).action == "ignore"


def test_green_ci_for_someone_else_is_ignored():
    decision = decide(event(conclusion="success", failed_jobs=(), pr_author="travism26"))
    assert decision.action == "ignore"


def test_review_pass_after_green_ci_settles_on_pull_request_target():
    decision = decide(event(event="pull_request_target", conclusion="success",
                            failed_jobs=(), comments=(_pass(),)))
    assert decision.action == "settle" and decision.clear_in_progress
    assert decision.comment == ""


def test_a_head_with_in_progress_already_off_is_left_alone():
    decision = decide(event(conclusion="success", failed_jobs=(), issue_labels=()))
    assert decision.action == "ignore" and decision.comment == ""


def test_excerpt_is_bounded_and_secret_free():
    planted = "super-secret-token-value"
    lines = [f"line {i}" for i in range(100)]
    lines.append(f"token {TOKEN} and {planted}")
    lines.append("FAIL: TestOnlyPostMessages")
    text = bound_excerpt("\n".join(lines), [planted])
    assert TOKEN not in text and planted not in text and "ghp_" not in text
    assert "[REDACTED]" in text and "TestOnlyPostMessages" in text
    assert "line 0" not in text and text.startswith("[...truncated]")
    short = bound_excerpt("one line\n", [])
    assert short == "one line" and not short.startswith("[...truncated]")


def test_failed_findings_name_only_failed_jobs_and_a_missing_log():
    jobs = [{"id": 1, "name": "factory tests", "conclusion": "success"},
            {"id": 2, "name": "check ai-gateway", "conclusion": "failure"},
            {"id": 3, "name": "check other", "conclusion": "failure"}]
    found = failed_findings(jobs, {2: "boom " + TOKEN}, [])
    assert [job.name for job in found] == ["check ai-gateway", "check other"]
    assert "boom" in found[0].excerpt and TOKEN not in found[0].excerpt
    assert found[1].excerpt == "(log unavailable)"


def test_a_review_run_is_the_pull_request_target_event():
    sha = SHA
    runs = [
        {"headSha": sha, "event": "push", "conclusion": "success"},
        {"headSha": sha, "event": "pull_request_target", "conclusion": "success", "databaseId": 2},
        {"headSha": "a" * 40, "event": "pull_request", "conclusion": "failure", "databaseId": 3},
    ]
    chosen = select_head_run(runs, sha)
    assert chosen["databaseId"] == 2
    assert select_head_run(runs, "b" * 40) is None


def test_wait_stays_pending_until_the_failure_comment_and_the_review_exist():
    assert not inputs_ready(None, None, [], SHA)
    ci = {"conclusion": "failure", "databaseId": 5}
    assert not inputs_ready(ci, None, [], SHA)
    ci_comment = {"body": "\n".join([MARKER, gate_line(SHA, True, "ci", ci_run=5),
                                     "## Factory review: BLOCKED"])}
    assert not inputs_ready(ci, {"conclusion": ""}, [ci_comment], SHA)
    review = {"body": "\n".join([MARKER, gate_line(SHA, True, "review", nonce="aa"),
                                 "## Factory review: BLOCKED"])}
    assert inputs_ready(ci, {"conclusion": ""}, [ci_comment, review], SHA)
    assert inputs_ready(ci, {"conclusion": "success"}, [ci_comment], SHA)
    green = {"conclusion": "success", "databaseId": 6}
    assert inputs_ready(green, {"conclusion": ""}, [review], SHA)
    assert inputs_ready({"conclusion": "timed_out"}, {"conclusion": ""}, [review], SHA)
    assert inputs_ready({"conclusion": "skipped"}, {"conclusion": ""}, [review], SHA)
    assert not inputs_ready({"conclusion": "cancelled"}, {"conclusion": ""}, [], SHA)
    assert not inputs_ready({"conclusion": "timed_out"}, {"conclusion": ""}, [], SHA)


def test_wait_loop_polls_until_ready():
    review = {"body": "\n".join([MARKER, gate_line(SHA, False, "review"),
                                 "## Factory review: PASS"])}
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        if calls["n"] == 1:
            raise GitHubError("temporary")
        if calls["n"] < 3:
            return None, None, []
        return ({"conclusion": "success", "databaseId": 1}, {"conclusion": "success"}, [review])

    sleeps = []
    clock = {"t": 0.0}

    def sleep(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds

    status = wait_for_inputs(fetch, sleep, lambda: clock["t"], timeout=100, interval=15,
                             head_sha=SHA)
    assert status == "ready"
    assert sleeps == [15, 15]


def test_a_finished_failure_without_a_comment_stops_waiting_after_the_grace():
    review = {"body": "\n".join([MARKER, gate_line(SHA, False, "review"),
                                 "## Factory review: PASS"])}
    ci = {"conclusion": "failure", "databaseId": 5}
    clock = {"t": 0.0}

    def sleep(seconds):
        clock["t"] += seconds

    status = wait_for_inputs(lambda: (ci, {"conclusion": ""}, [review]), sleep,
                             lambda: clock["t"], timeout=1000, interval=15, head_sha=SHA,
                             failure_grace=30)
    assert status == "ready"
    assert clock["t"] == 30


def test_a_missing_ci_run_stops_waiting_once_review_is_ready():
    review = {"body": "\n".join([MARKER, gate_line(SHA, False, "review"),
                                 "## Factory review: PASS"])}
    clock = {"t": 0.0}

    def sleep(seconds):
        clock["t"] += seconds

    status = wait_for_inputs(lambda: (None, {"conclusion": ""}, [review]), sleep,
                             lambda: clock["t"], timeout=1000, interval=15, head_sha=SHA,
                             failure_grace=30)
    assert status == "ready"
    assert clock["t"] == 30


def test_wait_cannot_block_forever_when_inputs_never_become_ready():
    sleeps = []
    clock = {"t": 0.0}

    def sleep(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds

    status = wait_for_inputs(lambda: ({"conclusion": ""}, None, []), sleep,
                             lambda: clock["t"], timeout=30, interval=15, head_sha=SHA)
    assert status == "timeout"
    assert clock["t"] == 30 and sleeps == [15, 15]
    assert wait_for_inputs(lambda: ({"conclusion": ""}, None, []),
                           lambda seconds: (_ for _ in ()).throw(AssertionError(seconds)),
                           lambda: 0.0, timeout=30, interval=0, head_sha=SHA) == "timeout"


class FakeGitHub:
    def __init__(self, pr, comments=(), issue_labels=("in-progress",), jobs=(), log="",
                 head_repo=REPO):
        self._pr = pr
        self._issue_labels = issue_labels
        self._jobs = list(jobs)
        self._log = log
        self._head_repo = head_repo
        self.posted, self.added, self.removed = [], [], []
        self._thread = list(comments)
        self._next = 1 + len(comments)

    def open_prs_for_branch(self, repo, branch):
        return [{"number": self._pr["number"], "headRefOid": self._pr["headRefOid"]}]

    def pr(self, repo, number):
        return self._pr

    def pull_head_repo(self, repo, number):
        return self._head_repo

    def pr_comments(self, repo, number):
        return list(self._thread)

    def issue(self, repo, number):
        return {"labels": [{"name": name} for name in self._issue_labels]}

    def comment(self, repo, number, path):
        body = path.read_text()
        self.posted.append((number, body))
        comment_id = self._next
        self._thread.append({"id": comment_id, "body": body})
        self._next += 1
        return comment_id

    def update_comment(self, repo, comment_id, path):
        body = path.read_text()
        self.updated = body
        for item in self._thread:
            if item["id"] == comment_id:
                item["body"] = body

    def add_labels(self, repo, number, labels):
        self.added += list(labels)
        names = {label["name"] for label in self._pr["labels"]}
        for label in labels:
            if label not in names:
                self._pr["labels"].append({"name": label})

    def remove_labels(self, repo, number, labels):
        self.removed += list(labels)
        if number == self._pr["number"]:
            self._pr["labels"] = [label for label in self._pr["labels"]
                                  if label["name"] not in labels]
        else:
            self._issue_labels = tuple(name for name in self._issue_labels if name not in labels)

    def jobs(self, repo, run_id):
        return self._jobs

    def job_log(self, repo, job_id):
        return self._log


def _pr(labels=()):
    return {"number": 118, "state": "OPEN", "isDraft": True, "body": "Closes #114\n",
            "headRefOid": SHA, "author": {"login": "travism26-factory[bot]"},
            "labels": [{"name": name} for name in labels]}


def test_collect_writes_a_redacted_excerpt_for_the_failed_job(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_" + "z" * 20)
    gh = FakeGitHub(
        _pr(), jobs=[{"id": 1, "name": "factory tests", "conclusion": "success"},
                     {"id": 2, "name": "check ai-gateway", "conclusion": "failure"}],
        log="start\n" + TOKEN + "\n--- FAIL: TestOnlyPostMessages\n")
    import argparse
    ns = argparse.Namespace(
        repo=REPO, run_id=RUN, run_url="https://example.test/run", conclusion="failure",
        event="pull_request", head_branch="factory/issue-114", head_sha=SHA, head_repo=REPO,
        out=str(tmp_path))
    assert ci_gate.collect(ns, gh) == 0
    saved = json.loads((tmp_path / "event.json").read_text())
    assert [job["name"] for job in saved["failed_jobs"]] == ["check ai-gateway"]
    assert "TestOnlyPostMessages" in saved["failed_jobs"][0]["excerpt"]
    assert TOKEN not in saved["failed_jobs"][0]["excerpt"]
    assert "ghp_" not in (tmp_path / "event.json").read_text()


def test_apply_posts_the_finding_and_the_rework_labels(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "event.json").write_text(json.dumps({
        "conclusion": "failure", "event": "pull_request", "head_branch": "factory/issue-114",
        "head_sha": SHA, "head_repo": REPO, "repo": REPO, "run_id": RUN,
        "run_url": "https://example.test/run",
        "failed_jobs": [{"name": "check ai-gateway", "excerpt": "FAIL: TestOnlyPostMessages"}],
    }))
    gh = FakeGitHub(_pr(), comments=[_pass()])
    import argparse
    ns = argparse.Namespace(out=str(out), app_slug="travism26-factory")
    assert ci_gate.apply(ns, gh) == 0
    assert gh.added == ["rework", "rework:1"]
    assert gh.posted and "TestOnlyPostMessages" in gh.posted[0][1]
    assert gh.posted[0][0] == 118


def test_a_lost_charge_is_rewritten_and_moves_no_labels(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "event.json").write_text(json.dumps({
        "conclusion": "failure", "event": "pull_request", "head_branch": "factory/issue-114",
        "head_sha": SHA, "head_repo": REPO, "repo": REPO, "run_id": RUN,
        "run_url": "https://example.test/run",
        "failed_jobs": [{"name": "check ai-gateway", "excerpt": "FAIL: TestOnlyPostMessages"}],
    }))
    gh = FakeGitHub(_pr(), comments=[_pass()])
    prior = _charge(nonce="aa", number=0)
    original = gh.pr_comments

    def pr_comments(repo, number):
        comments = original(repo, number)
        if gh.posted:
            return [prior] + comments
        return comments

    gh.pr_comments = pr_comments
    import argparse
    assert ci_gate.apply(argparse.Namespace(out=str(out), app_slug="travism26-factory"), gh) == 0
    assert gh.added == [] and gh.removed == []
    assert "charged=0" in gh.updated and "counter stays" in gh.updated
    assert "Sent to rework:" not in gh.updated
    assert "TestOnlyPostMessages" in gh.updated


def test_apply_second_time_does_not_charge_again(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "event.json").write_text(json.dumps({
        "conclusion": "failure", "event": "pull_request", "head_branch": "factory/issue-114",
        "head_sha": SHA, "head_repo": REPO, "repo": REPO, "run_id": RUN,
        "run_url": "https://example.test/run",
        "failed_jobs": [{"name": "check ai-gateway", "excerpt": "FAIL: TestOnlyPostMessages"}],
    }))
    import argparse
    ns = argparse.Namespace(out=str(out), app_slug="travism26-factory")
    first = FakeGitHub(_pr(), comments=[_pass()])
    assert ci_gate.apply(ns, first) == 0
    second = FakeGitHub(
        _pr(labels=("rework", "rework:1")),
        comments=[_pass(), {"id": 2, "body": first.posted[0][1]}])
    assert ci_gate.apply(ns, second) == 0
    assert second.added == [] and second.removed == []
    assert second.posted == []
