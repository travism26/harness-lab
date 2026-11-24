"""The Run record of a Review run (docs/factory/README.md, "Run records").

`factory.run_record write --workflow review` calls `write_review` here. Like the
Implement run it holds the App token and trusts nothing in <out>: the identity comes
from the workflow's context, the numbers from <out>/result.json are checked field by
field, and `verdict` and `gate` are read back from GitHub, where only the bot's own
`apply` step wrote them: the bot's report comment (its first two lines and the one
sentence under the headline) and the pull request's state and labels. Whatever is
read is still checked against the fixed lists. The `project` is the one on the linked
Ticket's `project:<name>` label.

The one exception is a pull request that closed before `apply` ran: it posts no
report, so the verdict comes from <out>/findings.json, parsed strictly and reduced
to PASS or BLOCKED.
"""

from dataclasses import replace
from pathlib import Path

from factory import review_pr
from factory.github import GitHub, GitHubError, label_names
from factory.record import (
    MAX_FILE,
    Outcomes,
    RunContext,
    bot_comments,
    build_record,
    failure_reason,
    leave_record,
    read_numbers,
)
from factory.ticket import PROJECT_PREFIX

# The sentence `render_report` writes under "Reviewed ..." for each outcome that moves
# no labels. Tests run `apply` and this step together, so a change there shows here.
_SENTENCES = (
    ("The PR is labelled", "human-owned"),
    ("The PR has moved on", "stale"),
    ("This head is already in a rework round", "same-round"),
    ("Spec passed. Required CI failed", "ci-blocked"),
)


def reports(
    comments: list[dict], app_slug: str, unrecorded: bool = True
) -> list[tuple[dict, review_pr.GateMark]]:
    """The review reports the bot posted, each with its gate line. By default only those
    that hold no record yet."""
    found = []
    for c in bot_comments(comments, app_slug, unrecorded):
        if not c["body"].startswith(review_pr.MARKER + "\n"):
            continue
        meta = review_pr.parse_gate(c["body"])
        if meta and meta.source == "review":
            found.append((c, meta))
    return found


def find_report(
    comments: list[dict], app_slug: str, head_sha: str, unrecorded: bool = True
) -> dict | None:
    """The newest report the bot posted for this head."""
    found = [
        c
        for c, meta in reports(comments, app_slug, unrecorded)
        if meta.head == head_sha
    ]
    return max(found, key=lambda c: c["id"]) if found else None


def gate_of(body: str) -> str | None:
    meta = review_pr.parse_gate(body)
    if meta and meta.charged:
        if review_pr.is_stopped(meta.add):
            return "human"
        return "rework" if review_pr.REWORK_LABEL in meta.add else None
    lines = body.split("\n")
    sentence = lines[5] if len(lines) > 5 else ""
    if not sentence:
        return "pass"
    for prefix, gate in _SENTENCES:
        if sentence.startswith(prefix):
            return gate
    return None


def _findings_verdict(out: Path) -> str | None:
    try:
        path = out / "findings.json"
        if path.stat().st_size > MAX_FILE:
            return None
        findings = review_pr.findings_from_json(path.read_text())
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return "BLOCKED" if findings.blocker else "PASS"


def project_of(gh: GitHub, repo: str, ticket: int | None) -> str | None:
    """The Project the linked Ticket names with its one `project:<name>` label, or None."""
    if not ticket:
        return None
    try:
        names = [
            n[len(PROJECT_PREFIX) :]
            for n in label_names(gh.issue(repo, ticket))
            if n.startswith(PROJECT_PREFIX)
        ]
    except GitHubError as e:
        print(f"::warning title=Run record::could not read the Ticket: {e}")
        return None
    return names[0] if len(names) == 1 else None


def write_review(args, gh: GitHub) -> int:
    """`args.agent_outcome` is the Review (agent) step's outcome and
    `args.publish_outcome` is the apply step's."""
    out = Path(args.out)
    numbers = read_numbers(out)
    pr_number = args.pr
    pr = {}
    try:
        pr = gh.pr(args.repo, pr_number)
    except GitHubError as e:
        print(f"::warning title=Run record::could not read the pull request: {e}")
    ticket = review_pr.linked_ticket(pr.get("body") or "", args.repo) if pr else None
    round_ = review_pr.rework_round(label_names(pr)) if pr else None

    target = verdict = gate = None
    outcome, reason = "fail", None
    outcomes = Outcomes(
        args.job_status, args.agent_outcome, publish=args.publish_outcome
    )
    if args.agent_outcome == "success":
        try:
            target = find_report(
                gh.pr_comments(args.repo, pr_number), args.app_slug, args.head_sha
            )
        except GitHubError as e:
            print(
                f"::warning title=Run record::could not read the pull request's comments: {e}"
            )
        if target:
            outcome = "ok"
            verdict = review_pr.review_verdict(target["body"])
            gate = gate_of(target["body"])
        elif pr and pr.get("state") != "OPEN":
            outcome, gate = "ok", "closed"
            verdict = _findings_verdict(out)
            if verdict is None:
                print(
                    "::warning title=Run record::the review's verdict could not be read"
                )
        else:
            reason = failure_reason(outcomes, numbers, review=True)
    else:
        reason = failure_reason(outcomes, numbers, review=True)

    ctx = replace(
        RunContext.from_args(args, ticket), project=project_of(gh, args.repo, ticket)
    )
    record = build_record(
        "review",
        ctx,
        numbers,
        outcome,
        reason,
        pr=pr_number,
        head_sha=args.head_sha,
        round_=round_,
        verdict=verdict,
        gate=gate,
    )
    if outcome == "ok":
        said = f" {record['verdict']}" if record["verdict"] else ""
        text = (
            f"Review finished after this pull request closed:{said}. "
            f"Nothing was changed. [run]({args.run_url})"
        )
    else:
        text = f"Review failed: `{record['reason']}`. [run]({args.run_url})"
    leave_record(gh, args.repo, pr_number, out, record, text, target)
    return 0
