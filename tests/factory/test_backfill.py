"""The backfill (`python -m factory.backfill`): a fake run listing and fixture artifacts in,
a JSONL file out. Assertions are on the file written, what is printed and the exit code."""
import json
from pathlib import Path

from factory import backfill, review_pr, ticket

FIXTURES = Path(__file__).parent / "fixtures"
REPO = "travism26/harness-lab"
SLUG = "travism26-factory"
HEAD = "c" * 40
AGENT_STEP = {"implement": "Build (agent, budget-capped, no GitHub token)",
              "rework": "Rework (agent, budget-capped, no GitHub token)",
              "review": "Review (fresh context, read-only, budget-capped)"}
# Text a transcript holds and a record must never hold.
MODEL_TEXT = "I will now rewrite the secret parser with great care"


def run(run_id, workflow, conclusion="success", attempt=1, branch="main",
        stamp="2026-11-13T22:27:29Z", started=None, pulls=()):
    return {"id": run_id, "name": workflow.capitalize(), "conclusion": conclusion,
            "status": "completed", "run_attempt": attempt, "head_branch": branch,
            "created_at": started or stamp, "updated_at": stamp,
            "pull_requests": [{"number": n} for n in pulls]}


def steps(workflow, agent="success", later=()):
    """The steps of a run's job: the agent step, then `later` as (name, conclusion) pairs."""
    return ([{"name": "Set up job", "conclusion": "success"},
             {"name": AGENT_STEP[workflow], "conclusion": agent}]
            + [{"name": name, "conclusion": conclusion} for name, conclusion in later])


def transcript(**changes):
    result = json.loads((FIXTURES / "result-success.json").read_text())
    result.update(changes)
    result["result"] = MODEL_TEXT
    lines = [{"type": "system", "subtype": "init"},
             {"type": "assistant", "message": {"content": MODEL_TEXT}}, result]
    return "\n".join(json.dumps(x) for x in lines) + "\n"


class FakeGH:
    def __init__(self):
        self.runs = {"implement": [], "rework": [], "review": []}
        self.attempts, self.jobs_, self.artifacts, self.files = {}, {}, {}, {}
        self.comments, self.prs, self.downloaded = {}, {}, []
        self.everywhere = []

    def add(self, r, workflow, agent="success", artifact=None, files=None, expired=False,
            later=()):
        self.runs[workflow].append(r)
        self.attempts[(r["id"], r["run_attempt"])] = r
        self.jobs_[(r["id"], r["run_attempt"])] = steps(workflow, agent, later)
        if artifact:
            self.artifacts.setdefault(r["id"], []).append({"name": artifact, "expired": expired})
            self.files[artifact] = files or {}

    def workflow_runs(self, repo, workflow):
        return list(self.runs[workflow])

    def attempt_run(self, repo, run_id, attempt):
        return self.attempts[(run_id, attempt)]

    def attempt_jobs(self, repo, run_id, attempt):
        return [{"steps": self.jobs_[(run_id, attempt)]}]

    def run_artifacts(self, repo, run_id):
        return list(self.artifacts.get(run_id, []))

    def download_artifact(self, repo, run_id, name, dest):
        self.downloaded.append(dest)
        for rel, text in self.files[name].items():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            (dest / rel).write_text(text)

    def pr_comments(self, repo, number):
        return list(self.comments.get(number, []))

    def repo_comments(self, repo):
        return list(self.everywhere)

    def pr(self, repo, number):
        return self.prs.get(number, {"body": ""})


def report(head, verdict="PASS", add=(), charged=False, id=5, at=None):
    gate = review_pr.gate_line(head, charged, "review", add=add)
    comment = {"id": id, "user": {"login": f"{SLUG}[bot]"},
               "body": f"{review_pr.MARKER}\n{gate}\n## Factory review: {verdict}\n\n"
                       f"Reviewed `{head[:12]}` against Ticket #7.\n"}
    return dict(comment, created_at=at) if at else comment


def bot_says(id, body, at="2026-11-13T22:27:20Z", issue=None):
    comment = {"id": id, "user": {"login": f"{SLUG}[bot]"}, "body": body, "created_at": at}
    return dict(comment, issue_url=f"https://api.github.com/repos/{REPO}/issues/{issue}") if issue else comment


def go(gh, tmp_path, *extra):
    out = tmp_path / "records.jsonl"
    code = backfill.main(["--repo", REPO, "--out", str(out), "--scratch", str(tmp_path / "s"),
                          *extra], gh=gh)
    rows = [json.loads(x) for x in out.read_text().splitlines()] if out.exists() else []
    return code, rows, out


def implement_ok(gh, run_id=100, **kw):
    gh.add(run(run_id, "implement", **kw), "implement",
           artifact=f"implement-issue116-run{run_id}-1",
           files={"agent.jsonl": transcript(),
                  "context.json": json.dumps({"repo": REPO, "issue": 116, "pr": None,
                                              "project": "ai-gateway"})})


def test_implement_run_with_an_artifact_gets_a_backfilled_record(tmp_path, capsys):
    gh = FakeGH()
    implement_ok(gh)
    gh.comments[116] = [{"id": 1, "user": {"login": f"{SLUG}[bot]"},
                         "body": f"The factory opened a draft PR: https://github.com/{REPO}/pull/135\n"}]
    code, rows, _ = go(gh, tmp_path)
    assert code == 0
    assert rows == [{
        "schema": 1, "ts": "2026-11-13T22:27:29Z", "workflow": "implement", "run_id": 100,
        "attempt": 1, "repo": REPO, "issue": 116, "pr": 135, "project": "ai-gateway",
        "login": None, "model": None, "budget": None, "model_ids": ["claude-sonnet-5-5"],
        "claude_code_version": None, "round": 0, "outcome": "ok", "reason": None,
        "verdict": None, "gate": None, "cost_usd": 0.1289566, "cost_note": "client-estimate",
        "turns": 5, "duration_ms": 40915, "input_tokens": 10, "output_tokens": 4592,
        "cache_creation_input_tokens": 18389, "cache_read_input_tokens": 94606,
        "head_sha": None, "backfilled": True}]
    assert "1 records (1 with numbers, 0 without numbers)" in capsys.readouterr().out


def test_run_without_an_artifact_keeps_identity_and_has_null_numbers(tmp_path, capsys):
    gh = FakeGH()
    gh.add(run(200, "review", conclusion="failure", branch="factory/issue-17"), "review")
    code, rows, _ = go(gh, tmp_path)
    (row,) = rows
    assert code == 0
    assert (row["run_id"], row["workflow"], row["issue"], row["outcome"]) == (200, "review", 17, "fail")
    assert all(row[k] is None for k in ("cost_usd", "turns", "duration_ms", "input_tokens",
                                        "output_tokens", "cache_creation_input_tokens",
                                        "cache_read_input_tokens", "verdict", "gate"))
    assert row["model_ids"] == [] and row["backfilled"] is True
    assert "0 with numbers, 1 without numbers" in capsys.readouterr().out


def test_expired_artifact_counts_as_no_artifact(tmp_path):
    gh = FakeGH()
    gh.add(run(201, "rework"), "rework", artifact="rework-pr5-run201-1", expired=True,
           files={"agent.jsonl": transcript()})
    _, rows, _ = go(gh, tmp_path)
    assert rows[0]["cost_usd"] is None and gh.downloaded == []


def test_runs_that_started_no_agent_get_no_record(tmp_path, capsys):
    gh = FakeGH()
    gh.add(run(300, "review", conclusion="failure"), "review", agent="skipped")
    gh.add(run(301, "implement", conclusion="skipped"), "implement")
    gh.add({**run(302, "implement"), "status": "in_progress", "conclusion": None}, "implement")
    code, rows, _ = go(gh, tmp_path)
    assert (code, rows) == (0, [])
    assert "0 records" in capsys.readouterr().out


def test_review_verdict_and_gate_come_from_the_report_comment(tmp_path):
    gh = FakeGH()
    ctx = {"repo": REPO, "pr": 135, "head_sha": HEAD, "ticket": 116}
    gh.add(run(400, "review", branch="factory/issue-116"), "review",
           artifact="review-pr135-run400-1",
           files={"agent.jsonl": transcript(), "context.json": json.dumps(ctx)})
    gh.comments[135] = [report(HEAD, "BLOCKED", add=("rework", "rework:1"), charged=True)]
    _, rows, _ = go(gh, tmp_path)
    (row,) = rows
    assert (row["pr"], row["issue"], row["head_sha"]) == (135, 116, HEAD)
    assert (row["verdict"], row["gate"], row["round"]) == ("BLOCKED", "rework", 1)


def test_review_without_a_report_has_null_verdict_and_gate(tmp_path):
    gh = FakeGH()
    ctx = {"repo": REPO, "pr": 135, "head_sha": HEAD}
    gh.add(run(401, "review"), "review", artifact="review-pr135-run401-1",
           files={"agent.jsonl": transcript(), "context.json": json.dumps(ctx)})
    _, rows, _ = go(gh, tmp_path)
    assert rows[0]["verdict"] is None and rows[0]["gate"] is None
    assert rows[0]["cost_usd"] == 0.1289566


def test_rework_round_comes_from_the_charging_comment(tmp_path):
    gh = FakeGH()
    ctx = {"repo": REPO, "issue": 128, "pr": 133, "project": None}
    gh.add(run(500, "rework"), "rework", artifact="rework-pr133-run500-1",
           files={"agent.jsonl": transcript(), "context.json": json.dumps(ctx)})
    gh.comments[133] = [report(HEAD, "BLOCKED", add=("rework", "rework:2"), charged=True)]
    _, rows, _ = go(gh, tmp_path)
    assert (rows[0]["round"], rows[0]["pr"], rows[0]["issue"]) == (2, 133, 128)


def test_every_attempt_of_a_run_gets_a_record(tmp_path):
    gh = FakeGH()
    gh.add(run(600, "review", conclusion="failure", stamp="2026-11-13T10:00:00Z"), "review",
           artifact="review-pr3-run600-1", files={"agent.jsonl": transcript()})
    gh.add(run(600, "review", attempt=2, stamp="2026-11-13T11:00:00Z"), "review",
           artifact="review-pr3-run600-2", files={"agent.jsonl": transcript()})
    gh.runs["review"] = [gh.attempts[(600, 2)]]       # the listing shows the latest attempt only
    _, rows, _ = go(gh, tmp_path)
    assert [(r["attempt"], r["outcome"], r["ts"]) for r in rows] == [
        (1, "fail", "2026-11-13T10:00:00Z"), (2, "ok", "2026-11-13T11:00:00Z")]


def test_records_are_ordered_and_a_second_run_gives_the_same_bytes(tmp_path):
    gh = FakeGH()
    implement_ok(gh, 900)
    gh.add(run(700, "review"), "review")
    implement_ok(gh, 800)
    _, rows, out = go(gh, tmp_path)
    first = out.read_bytes()
    assert [r["run_id"] for r in rows] == [700, 800, 900]
    go(gh, tmp_path)
    assert out.read_bytes() == first


def test_output_holds_no_transcript_text_and_no_token_shaped_string(tmp_path):
    gh = FakeGH()
    leak = "sk-ant-api03-AAAAAAAAAAAAAAAA"
    gh.add(run(1000, "implement"), "implement", artifact="implement-issue9-run1000-1",
           files={"agent.jsonl": transcript(modelUsage={leak: {"inputTokens": 1}}),
                  "context.json": json.dumps({"repo": REPO, "issue": 9, "project": leak})})
    code, rows, out = go(gh, tmp_path)
    text = out.read_text()
    assert code == 0 and MODEL_TEXT not in text and "sk-ant" not in text
    assert rows[0]["project"] is None and rows[0]["model_ids"] == []


def test_the_download_is_deleted_and_a_scratch_inside_the_repo_is_refused(tmp_path, capsys):
    gh = FakeGH()
    implement_ok(gh)
    go(gh, tmp_path)
    assert list((tmp_path / "s").iterdir()) == []
    inside = Path(backfill.__file__).resolve().parent.parent / "scratch-should-not-exist"
    capsys.readouterr()
    code = backfill.main(["--repo", REPO, "--out", str(tmp_path / "x.jsonl"),
                          "--scratch", str(inside)], gh=gh)
    assert code != 0 and not inside.exists() and not (tmp_path / "x.jsonl").exists()
    assert "inside the repo" in capsys.readouterr().err


# ---- what the jobs, the comments and the clock establish (code review B5) -----------------

def runs_url(run_id):
    return f"https://github.com/{REPO}/actions/runs/{run_id}"


def failed_comment(run_id, extra=""):
    return bot_says(1, f"{ticket.failed_prefix(runs_url(run_id))}. `in-progress` has been "
                       f"removed; re-apply `ready-for-factory` to try again.\n{extra}",
                    at="2026-11-13T22:25:00Z", issue=116)


def failed_implement(gh, run_id, step, conclusion="failure", agent_files=None):
    gh.add(run(run_id, "implement", "failure", started="2026-11-13T22:20:00Z"), "implement",
           later=[(step, conclusion)], artifact=f"implement-issue116-run{run_id}-1",
           files=agent_files or {"agent.jsonl": transcript(),
                                 "context.json": json.dumps({"repo": REPO, "issue": 116})})


def test_a_failed_check_step_is_check_failed(tmp_path):
    gh = FakeGH()
    failed_implement(gh, 1100, "Run the new Project check")
    _, (row,), _ = go(gh, tmp_path)
    assert (row["outcome"], row["reason"]) == ("fail", "check-failed")


def test_a_failed_publish_step_is_no_change_when_the_bots_failed_comment_says_nothing_changed(tmp_path):
    gh = FakeGH()
    failed_implement(gh, 1101, "Commit, push and open the draft PR")
    gh.comments[116] = [failed_comment(1101, f"\n{ticket.UNCHANGED}\n")]
    _, (row,), _ = go(gh, tmp_path)
    assert row["reason"] == "no-change"


def test_a_failed_publish_step_is_publish_failed_otherwise(tmp_path):
    gh = FakeGH()
    failed_implement(gh, 1102, "Commit, push and open the draft PR")
    gh.comments[116] = [failed_comment(1102), failed_comment(1103, f"\n{ticket.UNCHANGED}\n")]
    _, (row,), _ = go(gh, tmp_path)
    assert row["reason"] == "publish-failed"


def test_a_review_step_that_failed_after_a_success_result_line_is_unparsed_findings(tmp_path):
    gh = FakeGH()
    gh.add(run(1200, "review", "failure"), "review", agent="failure",
           artifact="review-pr135-run1200-1", files={"agent.jsonl": transcript()})
    _, (row,), _ = go(gh, tmp_path)
    assert row["reason"] == "unparsed-findings" and row["turns"] == 5


def test_a_failure_nothing_establishes_has_a_null_reason(tmp_path):
    gh = FakeGH()
    gh.add(run(1201, "rework", "failure"), "rework", artifact="rework-pr5-run1201-1",
           files={"agent.jsonl": transcript()})
    _, (row,), _ = go(gh, tmp_path)
    assert row["outcome"] == "fail" and row["reason"] is None


def test_a_review_report_that_charged_nothing_gets_the_round_in_force(tmp_path):
    gh = FakeGH()
    ctx = {"repo": REPO, "pr": 135, "head_sha": HEAD, "ticket": 116}
    gh.add(run(1300, "review", started="2026-11-13T22:20:00Z"), "review",
           artifact="review-pr135-run1300-1",
           files={"agent.jsonl": transcript(), "context.json": json.dumps(ctx)})
    gh.add(run(1301, "review", started="2026-11-13T20:00:00Z", stamp="2026-11-13T20:05:00Z"),
           "review", artifact="review-pr135-run1301-1",
           files={"agent.jsonl": transcript(), "context.json": json.dumps(dict(ctx, head_sha="e" * 40))})
    gh.comments[135] = [
        report("d" * 40, "BLOCKED", add=("rework", "rework:1"), charged=True, id=3,
               at="2026-11-13T21:00:00Z"),
        report(HEAD, "PASS", id=7, at="2026-11-13T22:25:00Z"),
        report("e" * 40, "PASS", id=2, at="2026-11-13T20:04:00Z")]
    _, rows, _ = go(gh, tmp_path)
    by_run = {r["run_id"]: r for r in rows}
    assert (by_run[1300]["verdict"], by_run[1300]["gate"], by_run[1300]["round"]) == ("PASS", "pass", 1)
    assert by_run[1301]["round"] == 0


def test_a_review_whose_artifact_is_gone_finds_its_report_by_the_clock(tmp_path):
    gh = FakeGH()
    gh.add(run(1400, "review", started="2026-11-13T22:20:00Z", pulls=[135]), "review")
    gh.prs[135] = {"body": "Closes #116"}
    gh.comments[135] = [
        report("d" * 40, "PASS", id=2, at="2026-11-13T21:00:00Z"),
        report(HEAD, "BLOCKED", add=("rework", "rework:1"), charged=True, id=9,
               at="2026-11-13T22:25:00Z"),
        report("e" * 40, "PASS", id=11, at="2026-11-13T23:59:00Z")]
    _, (row,), _ = go(gh, tmp_path)
    assert (row["head_sha"], row["verdict"], row["gate"], row["round"]) == (
        HEAD, "BLOCKED", "rework", 1)
    assert (row["pr"], row["issue"], row["cost_usd"]) == (135, 116, None)


def test_an_implement_run_with_no_artifact_takes_its_issue_from_the_comment_that_links_it(tmp_path):
    gh = FakeGH()
    gh.add(run(1500, "implement", "failure"), "implement")
    gh.add(run(1501, "implement", "failure"), "implement")
    gh.everywhere = [
        bot_says(1, f"The factory run for this Ticket failed: [run]({runs_url(1500)}). x", issue=77),
        bot_says(2, f"unrelated [run]({runs_url(15000)})", issue=5),
        {"id": 3, "user": {"login": "someone"}, "issue_url": f"https://x/issues/6",
         "body": f"[run]({runs_url(1501)})"}]
    _, rows, _ = go(gh, tmp_path)
    assert {r["run_id"]: r["issue"] for r in rows} == {1500: 77, 1501: None}


def test_a_skipped_publish_step_is_not_a_publish_failure(tmp_path):
    gh = FakeGH()
    failed_implement(gh, 1104, "Commit, push and open the draft PR", conclusion="skipped")
    _, (row,), _ = go(gh, tmp_path)
    assert row["outcome"] == "fail" and row["reason"] is None


def old_report(head, verdict="PASS", sentence="", id=5, ticket=7):
    """A report from before the gate line: the marker, the headline, then `Reviewed ...`."""
    lines = [review_pr.MARKER, f"## Factory review: {verdict}", "",
             f"Reviewed `{head[:12]}` against Ticket #{ticket}."]
    if sentence:
        lines.append(sentence)
    lines += ["", "### Spec: PASS", "", "PLACEHOLDER SUMMARY"]
    return {"id": id, "user": {"login": f"{SLUG}[bot]"}, "body": "\n".join(lines) + "\n"}


def review_with(gh, run_id, comments, head=HEAD, pr=135):
    ctx = {"repo": REPO, "pr": pr, "head_sha": head, "ticket": 7}
    gh.add(run(run_id, "review"), "review", artifact=f"review-pr{pr}-run{run_id}-1",
           files={"agent.jsonl": transcript(), "context.json": json.dumps(ctx)})
    gh.comments[pr] = comments


def test_a_report_from_before_the_gate_line_is_matched_by_the_head_it_names(tmp_path):
    gh = FakeGH()
    review_with(gh, 1600, [old_report("d" * 40, "BLOCKED", "Sent to rework: round 1 of 2.", id=3),
                           old_report(HEAD, "PASS", id=4)])
    (row,) = go(gh, tmp_path)[1]
    assert (row["verdict"], row["gate"], row["round"]) == ("PASS", "pass", 1)


def test_older_reports_give_the_gate_their_sentence_names(tmp_path):
    gh = FakeGH()
    review_with(gh, 1601, [old_report(HEAD, "BLOCKED", "Sent to rework: round 2 of 2.")])
    review_with(gh, 1602, [old_report(HEAD, "BLOCKED",
                                      "Review blocked this PR again after 2 rework rounds, "
                                      "so it is labelled `ready-for-human` and the factory "
                                      "stops here.")], pr=136)
    rows = {r["run_id"]: r for r in go(gh, tmp_path)[1]}
    assert (rows[1601]["verdict"], rows[1601]["gate"], rows[1601]["round"]) == ("BLOCKED", "rework", 2)
    assert (rows[1602]["verdict"], rows[1602]["gate"], rows[1602]["round"]) == ("BLOCKED", "human", 2)


def test_an_older_report_for_another_head_or_from_another_user_gives_no_verdict(tmp_path):
    gh = FakeGH()
    other = dict(old_report(HEAD, "PASS", id=4), user={"login": "someone"})
    review_with(gh, 1603, [old_report("d" * 40, "PASS", id=3), other])
    (row,) = go(gh, tmp_path)[1]
    assert (row["verdict"], row["gate"]) == (None, None)


def test_a_headline_that_is_neither_pass_nor_blocked_gives_no_verdict(tmp_path):
    gh = FakeGH()
    review_with(gh, 1604, [old_report(HEAD, "MAYBE", id=4)])
    (row,) = go(gh, tmp_path)[1]
    assert row["verdict"] is None
