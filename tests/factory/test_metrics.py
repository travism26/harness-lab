"""The metrics report (docs/factory/README.md, "Metrics report"), tested at its entry point:
a fixtures directory in, a markdown table and an exit code out."""

import json
from pathlib import Path

import pytest

from factory import metrics

FIXTURES = Path(__file__).parent / "fixtures" / "metrics"
BOT = "travism26-factory[bot]"


def _run(capsys, *argv):
    code = metrics.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _record(**kw):
    base = {
        "schema": 1,
        "ts": "2026-11-13T10:00:00Z",
        "workflow": "implement",
        "run_id": 1,
        "attempt": 1,
        "repo": "o/r",
        "issue": 5,
        "pr": None,
        "login": "subscription",
        "outcome": "ok",
        "reason": None,
        "verdict": None,
        "cost_usd": 0.5,
        "duration_ms": 60000,
    }
    base.update(kw)
    return base


def _marker(record):
    return "<!-- factory:run " + json.dumps(record) + " -->"


def _comment(id, body, login=BOT):
    return {
        "id": id,
        "user": {"login": login},
        "created_at": "2026-11-13T10:00:00Z",
        "body": body,
    }


def _fixtures(tmp_path, *comments):
    """A one-Ticket fixtures directory holding `comments`."""
    d = tmp_path / "fx" / "ticket-5"
    d.mkdir(parents=True)
    (d / "issue-comments.json").write_text(json.dumps(list(comments)))
    return tmp_path / "fx"


def test_the_golden_table_comes_from_the_fixtures_offline(capsys):
    code, out, err = _run(
        capsys,
        "--fixtures",
        str(FIXTURES),
        "--backfill",
        str(FIXTURES / "backfill.jsonl"),
    )
    assert code == 0, err
    assert out == (FIXTURES / "golden.md").read_text()


def test_live_mode_reads_the_same_facts_through_gh(capsys, monkeypatch):
    """`--repo` asks GitHub for each draft's timelines, pull request, commits and branch runs, and
    for main's subjects; a fake serving the fixtures must give the golden table."""

    def load(issue, name, default):
        path = FIXTURES / f"ticket-{issue}" / name
        return json.loads(path.read_text()) if path.is_file() else default

    class FakeGitHub:
        def __init__(self):
            self.calls = []

        def repo_comments(self, repo):
            return [
                c
                for d in sorted(FIXTURES.glob("ticket-*"))
                for n in metrics.COMMENT_FILES
                for c in (json.loads((d / n).read_text()) if (d / n).is_file() else [])
            ]

        def label_events(self, repo, number):
            self.calls.append(("label_events", number))
            issue = next(i for i in PRS if number in (i, PRS[i]))
            return load(
                issue,
                "issue-timeline.json" if number == issue else "pr-timeline.json",
                [],
            )

        def pull_api(self, repo, number):
            return load(next(i for i in PRS if PRS[i] == number), "pr.json", {})

        def pull_commits(self, repo, number):
            return load(next(i for i in PRS if PRS[i] == number), "pr-commits.json", [])

        def branch_runs(self, repo, branch):
            return load(int(branch.rsplit("-", 1)[1]), "ci-runs.json", {}).get(
                "workflow_runs", []
            )

        def main_subjects(self, repo):
            return json.loads((FIXTURES / "main-subjects.json").read_text())

    PRS = {
        int(d.name.split("-")[1]): load(int(d.name.split("-")[1]), "pr.json", {}).get(
            "number"
        )
        for d in FIXTURES.glob("ticket-*")
    }
    monkeypatch.setattr(metrics, "GitHub", FakeGitHub)
    code, out, err = _run(
        capsys,
        "--repo",
        "travism26/harness-lab",
        "--backfill",
        str(FIXTURES / "backfill.jsonl"),
    )
    assert code == 0, err
    assert out == (FIXTURES / "golden.md").read_text()


def test_a_marker_on_a_comment_the_bot_did_not_write_is_ignored(tmp_path, capsys):
    fx = _fixtures(
        tmp_path,
        _comment(1, "opened\n" + _marker(_record(pr=9, cost_usd=0.5))),
        _comment(2, _marker(_record(run_id=2, cost_usd=99.0)), login="travism26"),
    )
    code, out, _ = _run(capsys, "--fixtures", str(fx))
    assert code == 0
    assert "$0.50" in out
    assert "99" not in out


def test_two_attempts_of_one_run_both_count_toward_cost(tmp_path, capsys):
    fx = _fixtures(
        tmp_path,
        _comment(1, _marker(_record(attempt=1, cost_usd=0.5, outcome="fail"))),
        _comment(2, _marker(_record(attempt=2, cost_usd=0.25, pr=9))),
        _comment(3, _marker(_record(attempt=2, cost_usd=0.25, pr=9))),
    )
    code, out, _ = _run(capsys, "--fixtures", str(fx))
    assert code == 0
    assert "$0.75" in out


def test_a_record_with_an_unknown_schema_is_refused(tmp_path, capsys):
    fx = _fixtures(tmp_path, _comment(1, _marker(_record(schema=2))))
    code, out, err = _run(capsys, "--fixtures", str(fx))
    assert code == 1
    assert out == ""
    assert "schema 2" in err


def test_a_fixture_holding_a_token_shaped_string_is_rejected(tmp_path, capsys):
    fx = _fixtures(
        tmp_path,
        _comment(1, "opened\n" + _marker(_record(pr=9)) + "\nsk-ant-api03-abc123"),
    )
    code, out, err = _run(capsys, "--fixtures", str(fx))
    assert code == 1
    assert out == ""
    assert "token" in err
    assert "abc123" not in err


def test_a_marker_that_is_not_the_final_line_of_a_comment_is_ignored(tmp_path, capsys):
    """Code review A1: a copy quoted in a report is not the factory's record, and `schema 2`
    there does not make the whole report refuse."""
    quoted = _marker(_record(run_id=2, pr=999, cost_usd=99.0))
    fx = _fixtures(
        tmp_path,
        _comment(1, "opened\n" + _marker(_record(pr=9))),
        _comment(
            2, f"A finding quotes {quoted} and {_marker(_record(schema=2))}\nmore\n"
        ),
        _comment(3, f"{quoted} then text\n"),
        _comment(4, f"text {_marker(_record(run_id=3, cost_usd=98.0))}\n"),
    )
    code, out, err = _run(capsys, "--fixtures", str(fx))
    assert code == 0, err
    assert "$0.50" in out and "99" not in out and "98" not in out


def test_a_marker_followed_by_a_blank_line_is_still_the_final_line(tmp_path, capsys):
    fx = _fixtures(tmp_path, _comment(1, "opened\n" + _marker(_record(pr=9)) + "\n\n"))
    code, out, _ = _run(capsys, "--fixtures", str(fx))
    assert code == 0 and "$0.50" in out


def test_the_app_slug_is_derived_from_the_repo(tmp_path, capsys, monkeypatch):
    class FakeGitHub:
        def repo_comments(self, repo):
            return [
                _comment(
                    1, "opened\n" + _marker(_record(pr=9)), login="acme-factory[bot]"
                ),
                _comment(2, _marker(_record(run_id=2, cost_usd=99.0)), login=BOT),
            ]

        def label_events(self, repo, number):
            return []

        def pull_api(self, repo, number):
            return {}

        def pull_commits(self, repo, number):
            return []

        def branch_runs(self, repo, branch):
            return []

        def main_subjects(self, repo):
            return []

    monkeypatch.setattr(metrics, "GitHub", FakeGitHub)
    code, out, _ = _run(capsys, "--repo", "acme/widgets")
    assert code == 0 and "$0.50" in out and "99" not in out


def test_a_ticket_whose_records_name_no_login_prints_no_stray_comma(tmp_path, capsys):
    """Code review B2."""
    fx = _fixtures(
        tmp_path, _comment(1, "opened\n" + _marker(_record(pr=9, login=None)))
    )
    code, out, _ = _run(capsys, "--fixtures", str(fx))
    assert code == 0
    assert "$0.50 (est.)" in out and "(, est.)" not in out


def test_a_ticket_with_no_draft_lowers_the_draft_rate(tmp_path, capsys):
    fx = _fixtures(
        tmp_path,
        _comment(1, "opened\n" + _marker(_record(pr=9))),
        _comment(2, "failed\n" + _marker(_record(issue=6, run_id=2, outcome="fail"))),
    )
    code, out, _ = _run(capsys, "--fixtures", str(fx))
    assert code == 0
    total = next(line for line in out.splitlines() if line.startswith("| Total"))
    assert "1/2 (50%)" in total


def test_the_first_review_decides_first_pass(tmp_path, capsys):
    fx = _fixtures(
        tmp_path,
        _comment(1, "opened\n" + _marker(_record(pr=9))),
        _comment(
            2,
            _marker(
                _record(
                    workflow="review",
                    run_id=3,
                    pr=9,
                    verdict="BLOCKED",
                    ts="2026-11-13T11:00:00Z",
                )
            ),
        ),
        _comment(
            3,
            _marker(
                _record(
                    workflow="review",
                    run_id=2,
                    pr=9,
                    verdict="PASS",
                    ts="2026-11-13T12:00:00Z",
                )
            ),
        ),
    )
    code, out, _ = _run(capsys, "--fixtures", str(fx))
    assert code == 0
    total = next(line for line in out.splitlines() if line.startswith("| Total"))
    assert "0/1 (0%)" in total


def test_a_missing_source_is_an_error(tmp_path, capsys):
    code, out, err = _run(capsys, "--fixtures", str(tmp_path / "nope"))
    assert code == 1
    assert out == ""
    assert err


# ---- labels, pull requests, CI and git (ticket 146) --------------------------------

OWNER = "travism26"


def _label(action, name, actor, at):
    return {
        "event": action,
        "label": {"name": name},
        "actor": {"login": actor},
        "created_at": at,
    }


def _facts(
    tmp_path,
    *,
    events=(),
    pr_events=(),
    pr_state="closed",
    created="2026-11-13T10:02:00Z",
    merged="2026-11-13T10:30:00Z",
    commits=(),
    runs=(),
    main=None,
):
    """A one-Ticket fixtures directory (Ticket 5, pull request 9) in the real API shape."""
    fx = _fixtures(tmp_path, _comment(1, "opened\n" + _marker(_record(pr=9))))
    d = fx / "ticket-5"
    (d / "issue-timeline.json").write_text(json.dumps(list(events)))
    (d / "pr-timeline.json").write_text(json.dumps(list(pr_events)))
    (d / "pr.json").write_text(
        json.dumps(
            {
                "number": 9,
                "state": pr_state,
                "created_at": created,
                "merged_at": merged,
                "head": {"ref": "factory/issue-5"},
            }
        )
    )
    (d / "pr-commits.json").write_text(
        json.dumps(
            [
                {
                    "sha": f"{i:040d}",
                    "author": {"login": login},
                    "commit": {"author": {"name": login}, "message": "x"},
                }
                for i, login in enumerate(commits)
            ]
        )
    )
    (d / "ci-runs.json").write_text(
        json.dumps(
            {
                "workflow_runs": [
                    {
                        "name": n,
                        "event": "pull_request",
                        "conclusion": c,
                        "created_at": at,
                        "head_branch": "factory/issue-5",
                    }
                    for n, c, at in runs
                ]
            }
        )
    )
    if main is not None:
        (fx / "main-subjects.json").write_text(json.dumps(main))
    return fx


def _cells(capsys, fx):
    """The Ticket row and the totals row as {header: cell}."""
    code, out, err = _run(capsys, "--fixtures", str(fx))
    assert code == 0, err
    lines = out.splitlines()
    headers = [h.strip() for h in lines[0].strip("|").split("|")]
    rows = [
        dict(zip(headers, [c.strip() for c in line.strip("|").split("|")]))
        for line in lines[2:]
    ]
    return rows[0], rows[-1]


def test_rework_rounds_is_the_highest_round_the_bot_added(tmp_path, capsys):
    fx = _facts(
        tmp_path,
        pr_events=[
            _label("labeled", "rework", BOT, "2026-11-13T10:03:00Z"),
            _label("labeled", "rework:1", BOT, "2026-11-13T10:03:00Z"),
            _label("labeled", "rework:2", BOT, "2026-11-13T10:08:00Z"),
        ],
    )
    row, total = _cells(capsys, fx)
    assert row["Rework rounds"] == "2"
    assert total["Rework rounds"] == "2"


def test_a_hand_re_add_of_rework_does_not_raise_rework_rounds(tmp_path, capsys):
    fx = _facts(
        tmp_path,
        pr_events=[
            _label("labeled", "rework", BOT, "2026-11-13T10:03:00Z"),
            _label("labeled", "rework:1", BOT, "2026-11-13T10:03:00Z"),
            _label("labeled", "rework", OWNER, "2026-11-13T10:09:00Z"),
            _label("labeled", "rework:2", OWNER, "2026-11-13T10:09:00Z"),
        ],
    )
    row, _ = _cells(capsys, fx)
    assert row["Rework rounds"] == "1"


def test_owner_commits_counts_commits_the_bot_did_not_author(tmp_path, capsys):
    fx = _facts(tmp_path, commits=[BOT, OWNER, BOT, "cursoragent"])
    row, total = _cells(capsys, fx)
    assert row["Owner commits"] == "2"
    assert total["Owner commits"] == "2"


def test_a_pull_request_with_an_owner_commit_is_merged_but_not_untouched(
    tmp_path, capsys
):
    fx = _facts(tmp_path, commits=[BOT, OWNER])
    row, total = _cells(capsys, fx)
    assert row["Merge"] == "merged"
    assert row["Untouched merge"] == "no"
    assert total["Merge"] == "1/1 (100%)"
    assert total["Untouched merge"] == "0/1 (0%)"


def test_human_escalation_is_the_bot_adding_ready_for_human(tmp_path, capsys):
    fx = _facts(
        tmp_path,
        commits=[BOT],
        pr_events=[_label("labeled", "ready-for-human", BOT, "2026-11-13T10:20:00Z")],
    )
    row, total = _cells(capsys, fx)
    assert row["Human escalation"] == "yes"
    assert total["Human escalation"] == "1/1 (100%)"
    assert row["Untouched merge"] == "no"


def test_ready_for_human_added_by_hand_is_not_an_escalation_but_is_not_untouched(
    tmp_path, capsys
):
    """Code review B1: the human label counts for the merge, from anyone; the escalation rate is
    the bot's alone."""
    fx = _facts(
        tmp_path,
        commits=[BOT],
        pr_events=[_label("labeled", "ready-for-human", OWNER, "2026-11-13T10:20:00Z")],
    )
    row, total = _cells(capsys, fx)
    assert row["Human escalation"] == "no"
    assert total["Human escalation"] == "0/1 (0%)"
    assert row["Untouched merge"] == "no"
    assert total["Untouched merge"] == "0/1 (0%)"


def test_an_open_pull_request_counts_toward_neither_side_of_merge_rate(
    tmp_path, capsys
):
    fx = _facts(tmp_path, pr_state="open", merged=None)
    row, total = _cells(capsys, fx)
    assert row["Merge"] == "open"
    assert total["Merge"] == "n/a"


def test_a_pull_request_closed_unmerged_lowers_merge_rate(tmp_path, capsys):
    fx = _facts(tmp_path, pr_state="closed", merged=None)
    row, total = _cells(capsys, fx)
    assert row["Merge"] == "closed"
    assert total["Merge"] == "0/1 (0%)"
    assert row["Untouched merge"] == "no"


def test_ci_on_first_push_reads_the_first_ci_run_on_the_branch(tmp_path, capsys):
    fx = _facts(
        tmp_path,
        runs=[
            ("Review", "failure", "2026-11-13T10:02:00Z"),
            ("CI", "failure", "2026-11-13T10:03:00Z"),
            ("CI", "success", "2026-11-13T10:09:00Z"),
        ],
    )
    row, total = _cells(capsys, fx)
    assert row["CI on first push"] == "no"
    assert total["CI on first push"] == "0/1 (0%)"


def test_a_green_first_ci_run_counts_even_when_review_ran_first_and_failed(
    tmp_path, capsys
):
    fx = _facts(
        tmp_path,
        runs=[
            ("CI", "success", "2026-11-13T10:03:00Z"),
            ("Review", "failure", "2026-11-13T10:02:00Z"),
        ],
    )
    row, total = _cells(capsys, fx)
    assert row["CI on first push"] == "yes"
    assert total["CI on first push"] == "1/1 (100%)"


def test_a_branch_with_no_ci_run_is_not_a_green_first_push(tmp_path, capsys):
    fx = _facts(tmp_path, runs=[("Review", "success", "2026-11-13T10:02:00Z")])
    row, total = _cells(capsys, fx)
    assert row["CI on first push"] == "none"
    assert total["CI on first push"] == "0/1 (0%)"


@pytest.mark.parametrize("start", ["ready-for-agent", "ready-for-factory"])
def test_a_ticket_started_under_either_start_label_gives_a_start_to_draft_time(
    tmp_path, capsys, start
):
    fx = _facts(
        tmp_path,
        created="2026-11-13T10:02:00Z",
        events=[
            _label("labeled", start, OWNER, "2026-11-13T10:00:00Z"),
            _label("unlabeled", start, BOT, "2026-11-13T10:00:30Z"),
            _label("labeled", "in-progress", BOT, "2026-11-13T10:00:31Z"),
        ],
    )
    row, total = _cells(capsys, fx)
    assert row["Start label to draft"] == "1m 30s"
    assert total["Start label to draft"] == "1m 30s"


def test_start_to_draft_counts_from_the_last_start_label_removal_before_the_draft(
    tmp_path, capsys
):
    fx = _facts(
        tmp_path,
        created="2026-11-13T12:01:00Z",
        events=[
            _label("unlabeled", "ready-for-factory", BOT, "2026-11-13T10:00:00Z"),
            _label("unlabeled", "ready-for-factory", OWNER, "2026-11-13T11:30:00Z"),
            _label("unlabeled", "ready-for-factory", BOT, "2026-11-13T12:00:00Z"),
            _label("unlabeled", "ready-for-factory", BOT, "2026-11-13T13:00:00Z"),
        ],
    )
    row, _ = _cells(capsys, fx)
    assert row["Start label to draft"] == "1m 00s"


def test_a_draft_with_no_start_label_removal_has_no_start_to_draft_time(
    tmp_path, capsys
):
    fx = _facts(tmp_path)
    row, total = _cells(capsys, fx)
    assert row["Start label to draft"] == "n/a"
    assert total["Start label to draft"] == "n/a"


def test_a_later_main_subject_starting_with_revert_and_naming_the_pull_request_counts(
    tmp_path, capsys
):
    fx = _facts(
        tmp_path,
        main=[
            'Revert "Add the thing (#9)"',
            "Add the thing (#9)",
            'Revert "Another thing (#90)"',
            "Revert the flag default, see #9",
        ],
    )
    row, total = _cells(capsys, fx)
    assert row["Post-merge reverts"] == "2"
    assert total["Post-merge reverts"] == "2"


def test_a_pull_request_that_was_not_merged_has_no_post_merge_reverts(tmp_path, capsys):
    fx = _facts(
        tmp_path, pr_state="closed", merged=None, main=['Revert "Add the thing (#9)"']
    )
    row, _ = _cells(capsys, fx)
    assert row["Post-merge reverts"] == "0"


def test_a_pull_request_the_bot_alone_wrote_and_never_escalated_is_untouched(
    tmp_path, capsys
):
    fx = _facts(tmp_path, commits=[BOT, BOT])
    row, total = _cells(capsys, fx)
    assert row["Untouched merge"] == "yes"
    assert total["Untouched merge"] == "1/1 (100%)"


# ---- which Tickets count: the bot claimed them, or a record names them ------------

STARTED = (
    "The factory started this Ticket. [Run](https://github.com/o/r/actions/runs/1)\n"
)


def _claim(id, issue, body=STARTED, login=BOT):
    comment = _comment(id, body, login)
    comment["issue_url"] = (
        f"https://api.github.com/repos/travism26/harness-lab/issues/{issue}"
    )
    return comment


def _rows(out):
    return [line for line in out.splitlines() if line.startswith("| #")]


def test_a_ticket_the_bot_claimed_with_no_record_gets_a_row_and_counts_as_not_drafted(
    tmp_path, capsys
):
    drafted = _comment(
        1,
        "The factory opened a draft PR: https://github.com/o/r/pull/6\n\n"
        + _marker(_record(issue=5, pr=6)),
    )
    code, out, err = _run(
        capsys, "--fixtures", str(_fixtures(tmp_path, drafted, _claim(2, 30)))
    )
    assert code == 0, err
    row = next(r for r in _rows(out) if r.startswith("| #30 "))
    assert row.split(" | ")[1] == "no"
    assert "| Total (2) | 1/2 (50%) |" in out


def test_the_started_comment_from_a_login_that_is_not_the_bot_adds_no_row(
    tmp_path, capsys
):
    code, out, err = _run(
        capsys, "--fixtures", str(_fixtures(tmp_path, _claim(2, 30, login="someone")))
    )
    assert code == 0, err
    assert _rows(out) == []


def test_a_bot_comment_that_only_quotes_the_started_text_adds_no_row(tmp_path, capsys):
    code, out, err = _run(
        capsys,
        "--fixtures",
        str(_fixtures(tmp_path, _claim(2, 30, body="Earlier it said:\n> " + STARTED))),
    )
    assert code == 0, err
    assert _rows(out) == []


def test_a_ticket_with_both_the_started_comment_and_a_record_appears_once(
    tmp_path, capsys
):
    record = _comment(1, "The factory failed.\n\n" + _marker(_record(issue=30)))
    code, out, err = _run(
        capsys, "--fixtures", str(_fixtures(tmp_path, _claim(2, 30), record))
    )
    assert code == 0, err
    assert len([r for r in _rows(out) if r.startswith("| #30 ")]) == 1
    assert "| Total (1) |" in out
