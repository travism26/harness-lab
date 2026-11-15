"""The backfill (`python -m factory.backfill`): a fake run listing and fixture artifacts in,
a JSONL file out. Assertions are on the file written, what is printed and the exit code."""
import json
from pathlib import Path

from factory import backfill, review_pr

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
        stamp="2026-11-13T22:27:29Z"):
    return {"id": run_id, "name": workflow.capitalize(), "conclusion": conclusion,
            "status": "completed", "run_attempt": attempt, "head_branch": branch,
            "created_at": stamp, "updated_at": stamp, "pull_requests": []}


def steps(workflow, agent="success"):
    return [{"name": "Set up job", "conclusion": "success"},
            {"name": AGENT_STEP[workflow], "conclusion": agent}]


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

    def add(self, r, workflow, agent="success", artifact=None, files=None, expired=False):
        self.runs[workflow].append(r)
        self.attempts[(r["id"], r["run_attempt"])] = r
        self.jobs_[(r["id"], r["run_attempt"])] = steps(workflow, agent)
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

    def pr(self, repo, number):
        return self.prs.get(number, {"body": ""})


def report(head, verdict="PASS", add=(), charged=False):
    gate = review_pr.gate_line(head, charged, "review", add=add)
    return {"id": 5, "user": {"login": f"{SLUG}[bot]"},
            "body": f"{review_pr.MARKER}\n{gate}\n## Factory review: {verdict}\n\n"
                    f"Reviewed `{head[:12]}` against Ticket #7.\n"}


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
