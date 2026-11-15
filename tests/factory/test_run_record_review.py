"""The Run record of a Review run: `review_pr review` and `apply` run as the workflow runs them,
then `run_record write --workflow review`, with a fake agent and a fake GitHub. Assertions are on
the files in review-out/ and the comments posted."""
import argparse
import json
import re
from pathlib import Path

import pytest

from factory import review_pr, run_record
from factory.claude import Result
from factory.review_pr import parse_gate, review_input

FIXTURES = Path(__file__).parent / "fixtures"
REPO = "travism26/harness-lab"
HEAD = "c" * 40
RUN_URL = f"https://github.com/{REPO}/actions/runs/888"
BOT = "harness-factory[bot]"
PASS = {"spec_summary": "ok", "standards_summary": "ok", "spec_findings": [],
        "standards_findings": []}
BLOCK = dict(PASS, spec_findings=[{"kind": "missing_requirement", "description": "d",
                                   "resolution": "r", "file_path": None}])


class FakeGitHub:
    def __init__(self, labels=(), head=HEAD, state="OPEN", body="Closes #7", plant=None,
                 comments=()):
        self.state, self.head, self.body, self.labels = state, head, body, list(labels)
        self.plant, self.reads = plant, 0
        self.thread = [dict(c) for c in comments]
        self.posted = []

    def pr(self, repo, number):
        return {"number": number, "state": self.state, "body": self.body,
                "headRefOid": self.head, "labels": [{"name": n} for n in self.labels]}

    def pr_comments(self, repo, number):
        self.reads += 1
        extra = [{"id": 0, "body": self.plant}] if self.plant and self.reads > 1 else []
        return extra + [dict(c) for c in self.thread]

    def comment(self, repo, number, path):
        body = path.read_text()
        self.posted.append(body)
        cid = 100 + len(self.thread)
        self.thread.append({"id": cid, "body": body, "user": {"login": BOT}})
        return cid

    def update_comment(self, repo, comment_id, path):
        for c in self.thread:
            if c["id"] == comment_id:
                c["body"] = path.read_text()

    def add_labels(self, repo, number, labels):
        self.labels += list(labels)

    def remove_labels(self, repo, number, labels):
        self.labels = [n for n in self.labels if n not in labels]


def _review(out, answer=PASS, message=None, success=True, subtype="success", text=None,
            head=HEAD):
    out.mkdir(exist_ok=True)
    (out / "context.json").write_text(json.dumps(
        {"repo": REPO, "pr": 3, "base_sha": "b", "head_sha": head, "code_dir": "pr",
         "ticket": 7}))
    message = json.loads((FIXTURES / "result-success.json").read_text()) if message is None else message
    reply = json.dumps(answer) if text is None else text
    args = argparse.Namespace(out=str(out), login="subscription", model="sonnet",
                              max_budget_usd=2.0)
    try:
        review_pr.review(args, run_agent=lambda prompt, **kw: Result(success, reply, subtype,
                                                                     0.1, message))
        return "success"
    except RuntimeError:
        return "failure"


def _apply(out, gh, ci=None):
    if ci:
        (out / "ci-conclusion.txt").write_text(ci + "\n")
    # The report is posted by the bot; the fake attributes every comment to it.
    return review_pr.apply(argparse.Namespace(repo=REPO, pr=3, out=str(out)), gh)


def _last(out, gh, review="success", apply="success", job="success", **kw):
    base = dict(workflow="review", out=str(out), repo=REPO, run_id="888", attempt="1",
                issue=None, pr=3, head_sha=HEAD, project="", login="subscription",
                model="sonnet", budget="2", claude_code_version="2.1.319", app_slug="harness-factory",
                run_url=RUN_URL, job_status=job, build_outcome=review, verify_outcome="skipped",
                publish_outcome=apply)
    base.update(kw)
    return run_record.write(argparse.Namespace(**base), gh)


def _marker(body):
    found = re.findall(r"<!-- factory:run (\{.*?\}) -->", body)
    assert len(found) == 1
    return json.loads(found[0])


def _record(out):
    return json.loads((out / "run.json").read_text())


def _whole(tmp_path, gh, answer=PASS, ci=None):
    out = tmp_path / "review-out"
    assert _review(out, answer) == "success"
    _apply(out, gh, ci)
    assert _last(out, gh) == 0
    return out, _record(out)


def test_a_passing_review_leaves_a_record_in_a_file_and_on_its_report(tmp_path):
    gh = FakeGitHub()
    out, record = _whole(tmp_path, gh)
    assert len(gh.thread) == 1 and gh.thread[0]["body"].count("factory:run") == 1
    assert _marker(gh.thread[0]["body"]) == record
    assert (record["outcome"], record["reason"], record["verdict"], record["gate"]) == (
        "ok", None, "PASS", "pass")
    assert (record["workflow"], record["pr"], record["issue"], record["head_sha"]) == (
        "review", 3, 7, HEAD)
    assert (record["turns"], record["cost_usd"], record["model_ids"]) == (
        5, 0.1289566, ["claude-sonnet-5-5"])


def test_the_marker_leaves_the_first_two_lines_and_the_existing_readers_working(tmp_path):
    gh = FakeGitHub()
    _whole(tmp_path, gh, BLOCK)
    body = gh.thread[0]["body"]
    lines = body.splitlines()
    assert lines[0] == review_pr.MARKER and parse_gate(lines[1]).head == HEAD
    assert parse_gate(body).charged and review_pr.review_verdict(body) == "BLOCKED"
    assert review_input(gh.thread, HEAD) == body


GATES = {
    "pass": dict(gh=dict(), answer=PASS, verdict="PASS", round=0),
    "rework": dict(gh=dict(), answer=BLOCK, verdict="BLOCKED", round=1),
    "human": dict(gh=dict(labels=["rework", "rework:2"]), answer=BLOCK, verdict="BLOCKED",
                  round=2),
    "human-owned": dict(gh=dict(labels=["ready-for-human"]), answer=BLOCK, verdict="BLOCKED",
                        round=0),
    "ci-blocked": dict(gh=dict(), answer=PASS, verdict="PASS", round=0, ci="failure"),
}


@pytest.mark.parametrize("gate", list(GATES))
def test_each_gate_is_recorded(tmp_path, gate):
    spec = GATES[gate]
    gh = FakeGitHub(**spec["gh"])
    out, record = _whole(tmp_path, gh, spec["answer"], spec.get("ci"))
    assert (record["gate"], record["verdict"], record["round"], record["outcome"]) == (
        gate, spec["verdict"], spec["round"], "ok")
    assert _marker(gh.thread[0]["body"]) == record


def test_a_stale_review_records_stale(tmp_path):
    gh = FakeGitHub(head="d" * 40)
    out, record = _whole(tmp_path, gh)
    assert (record["gate"], record["head_sha"]) == ("stale", HEAD)


def test_a_lost_charge_race_records_the_corrected_gate(tmp_path):
    plant = review_pr.gate_line(HEAD, True, "ci", ci_run=9, nonce="aa", add=("rework", "rework:1"))
    gh = FakeGitHub(plant=plant)
    out, record = _whole(tmp_path, gh, BLOCK)
    assert (record["gate"], record["verdict"], record["round"]) == ("same-round", "BLOCKED", 0)
    body = gh.thread[0]["body"]
    assert "charged=0" in body and _marker(body) == record


def test_a_review_that_finishes_on_a_closed_pull_request_leaves_one_line(tmp_path):
    gh = FakeGitHub(state="MERGED")
    out, record = _whole(tmp_path, gh, BLOCK)
    assert (record["outcome"], record["verdict"], record["gate"]) == ("ok", "BLOCKED", "closed")
    assert len(gh.posted) == 1
    line = gh.posted[0]
    assert line.startswith("Review finished after this pull request closed: BLOCKED. Nothing was changed.")
    assert RUN_URL in line and review_pr.MARKER not in line and len(line.splitlines()) == 2
    assert _marker(line) == record


def test_a_pull_request_that_closes_no_ticket_gives_a_null_issue(tmp_path):
    gh = FakeGitHub(body="no keyword here")
    out, record = _whole(tmp_path, gh)
    assert record["issue"] is None


def test_the_command_line_accepts_a_missing_issue():
    args = run_record.main.__globals__["_issue"]
    assert args("") is None and args("null") is None and args("12") == 12


def _failed(tmp_path, **kw):
    out = tmp_path / "review-out"
    review = _review(out, **{k: v for k, v in kw.items() if k != "last"})
    gh = FakeGitHub()
    assert _last(out, gh, review=review, **kw.get("last", {})) == 0
    assert len(gh.posted) == 1 and len(gh.thread) == 1
    line = gh.posted[0]
    assert review_pr.MARKER not in line and RUN_URL in line and len(line.splitlines()) == 2
    record = _record(out)
    assert record["outcome"] == "fail" and _marker(line) == record
    assert record["verdict"] is None and record["gate"] is None
    return record, line


def test_a_cli_error_subtype_fails_the_review(tmp_path):
    message = json.loads((FIXTURES / "result-budget-stop.json").read_text())
    record, line = _failed(tmp_path, message=message, success=False, subtype="error_max_budget_usd")
    assert record["reason"] == "error_max_budget_usd"
    assert line.startswith("Review failed: `error_max_budget_usd`.")
    assert (record["input_tokens"], record["output_tokens"]) == (2, 56)


def test_a_review_with_no_result_line_fails_as_no_result(tmp_path):
    record, line = _failed(tmp_path, message={}, success=False, subtype="")
    assert record["reason"] == "no-result" and record["turns"] is None
    assert line.startswith("Review failed: `no-result`.")


def test_findings_that_do_not_parse_fail_as_unparsed_findings(tmp_path):
    record, line = _failed(tmp_path, text="I could not decide, sorry")
    assert record["reason"] == "unparsed-findings" and record["turns"] == 5
    assert "could not decide" not in line and "could not decide" not in json.dumps(record)


def test_a_cancelled_review_fails_as_cancelled(tmp_path):
    record, line = _failed(tmp_path, message={}, success=False, subtype="",
                           last=dict(job="cancelled"))
    assert record["reason"] == "cancelled"


def test_a_review_that_read_fine_but_never_posted_fails_as_publish_failed(tmp_path):
    out = tmp_path / "review-out"
    assert _review(out) == "success"
    gh = FakeGitHub()
    assert _last(out, gh, apply="failure") == 0
    assert _record(out)["reason"] == "publish-failed" and gh.posted[0].startswith("Review failed")


def test_a_forged_report_or_verdict_file_in_the_output_directory_changes_nothing(tmp_path):
    gh = FakeGitHub(state="OPEN")
    out = tmp_path / "review-out"
    assert _review(out, BLOCK) == "success"
    (out / "report.md").write_text(f"{review_pr.MARKER}\n## Factory review: PASS\n")
    (out / "run.json").write_text(json.dumps({"verdict": "PASS", "gate": "pass"}))
    (out / "context.json").write_text(json.dumps({"head_sha": "e" * 40, "ticket": 99}))
    _apply_ctx = json.dumps({"repo": REPO, "pr": 3, "base_sha": "b", "head_sha": HEAD,
                             "code_dir": "pr", "ticket": 7})
    # apply ran earlier with the real context; the last step must not read it again.
    (out / "context.json").write_text(_apply_ctx)
    _apply(out, gh)
    (out / "context.json").write_text(json.dumps({"head_sha": "e" * 40, "ticket": 99}))
    (out / "findings.json").write_text(json.dumps(PASS))
    assert _last(out, gh) == 0
    record = _record(out)
    assert (record["verdict"], record["gate"], record["issue"], record["head_sha"]) == (
        "BLOCKED", "rework", 7, HEAD)


def test_a_report_by_someone_else_or_for_another_head_is_not_used(tmp_path):
    out = tmp_path / "review-out"
    assert _review(out) == "success"
    fake = review_pr.MARKER + "\n" + review_pr.gate_line(HEAD, False, "review") + \
        "\n## Factory review: PASS\n"
    other = review_pr.MARKER + "\n" + review_pr.gate_line("d" * 40, False, "review") + \
        "\n## Factory review: PASS\n"
    gh = FakeGitHub(comments=[{"id": 1, "body": fake, "user": {"login": "stranger"}},
                              {"id": 2, "body": other, "user": {"login": BOT}}])
    assert _last(out, gh) == 0
    assert _record(out)["outcome"] == "fail"
    assert gh.thread[0]["body"] == fake and gh.thread[1]["body"] == other


def test_a_rerun_marks_its_own_report_and_leaves_the_first_attempts(tmp_path):
    gh = FakeGitHub()
    out, first = _whole(tmp_path, gh)
    second_out = tmp_path / "again"
    assert _review(second_out) == "success"
    _apply(second_out, gh)
    assert _last(second_out, gh, attempt="2") == 0
    assert len(gh.thread) == 2
    assert _marker(gh.thread[0]["body"])["attempt"] == 1
    assert _marker(gh.thread[1]["body"])["attempt"] == 2


def test_the_review_record_holds_no_model_text(tmp_path):
    message = dict(json.loads((FIXTURES / "result-success.json").read_text()),
                   result="SECRET MODEL WORDS")
    out = tmp_path / "review-out"
    assert _review(out, message=message, answer=dict(PASS, spec_summary="SECRET MODEL WORDS")) == "success"
    gh = FakeGitHub()
    _apply(out, gh)
    _last(out, gh)
    assert "SECRET MODEL WORDS" not in (out / "result.json").read_text()
    assert "SECRET MODEL WORDS" not in (out / "run.json").read_text()
    assert "MODEL WORDS" not in gh.thread[0]["body"].split("factory:run")[1]


def test_review_yml_runs_the_last_step_from_the_base_checkout_after_apply():
    text = (Path(__file__).parents[2] / ".github/workflows/review.yml").read_text()
    step = text.split("- name: Leave the run record")[1].split("- name: Keep")[0]
    assert text.index("Post the report and move the labels") < text.index("Leave the run record")
    assert text.index("Leave the run record") < text.index("Keep the review's files")
    assert "if: always() && steps.review.conclusion != 'skipped'" in step
    assert "python -m factory.run_record write --workflow review" in step
    command = step.split("run: >-")[1]
    assert "pr/" not in command and "secrets." not in step
