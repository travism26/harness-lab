"""The Run record of a Review run (docs/factory/README.md, "Run records").

`factory.run_record write --workflow review` calls `write_review` here. Like the
Implement run it holds the App token and trusts nothing in <out>: the identity comes
from the workflow's context, the numbers from <out>/result.json are checked field by
field, and `verdict` and `gate` are read back from GitHub, where only the bot's own
`apply` step wrote them: the bot's report comment (its first two lines and the one
sentence under the headline) and the pull request's state and labels. Whatever is
read is still checked against the fixed lists.

The one exception is a pull request that closed before `apply` ran: it posts no
report, so the verdict comes from <out>/findings.json, parsed strictly and reduced
to PASS or BLOCKED.
"""
import json
from pathlib import Path
from typing import List, Optional

from factory import review_pr
from factory import run_record as rr
from factory.github import GitHub, GitHubError, label_names, write_comment

# The sentence `render_report` writes under "Reviewed ..." for each outcome that moves
# no labels. Tests run `apply` and this step together, so a change there shows here.
_SENTENCES = (("The PR is labelled", "human-owned"), ("The PR has moved on", "stale"),
              ("This head is already in a rework round", "same-round"),
              ("Spec passed. Required CI failed", "ci-blocked"))


def _report(comments: List[dict], slug: str, head_sha: str) -> Optional[dict]:
    """The newest report the bot posted for this head that holds no record yet."""
    bot = f"{slug}[bot]".lower()
    found = []
    for c in comments:
        body = c.get("body")
        if not isinstance(body, str) or not body.startswith(review_pr.MARKER + "\n"):
            continue
        meta = review_pr.parse_gate(body)
        if (meta and meta.source == "review" and meta.head == head_sha
                and not rr.MARKER_RE.search(body)
                and str((c.get("user") or {}).get("login", "")).lower() == bot):
            found.append(c)
    return max(found, key=lambda c: c["id"]) if found else None


def _gate_of(body: str) -> Optional[str]:
    meta = review_pr.parse_gate(body)
    if meta and meta.charged:
        if review_pr.HUMAN_LABEL in meta.add:
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


def _findings_verdict(out: Path) -> Optional[str]:
    try:
        path = out / "findings.json"
        if path.stat().st_size > rr._MAX_FILE:
            return None
        findings = review_pr.findings_from_json(path.read_text())
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return "BLOCKED" if findings.blocker else "PASS"


def _failure_reason(args, numbers: dict) -> str:
    if "cancelled" in (args.job_status, args.build_outcome, args.publish_outcome):
        return "cancelled"
    subtype = numbers.get("subtype")
    if isinstance(subtype, str) and rr._SUBTYPE_RE.match(subtype):
        return subtype
    if subtype == "success" and numbers.get("is_error") is not True:
        return "unparsed-findings"
    return "no-result"


def write_review(args, gh: Optional[GitHub] = None) -> int:
    """`args.build_outcome` is the Review (agent) step's outcome and
    `args.publish_outcome` is the apply step's."""
    gh = gh or GitHub()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    numbers = rr.read_numbers(out)
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
    if args.build_outcome == "success":
        try:
            target = _report(gh.pr_comments(args.repo, pr_number), args.app_slug, args.head_sha)
        except GitHubError as e:
            print(f"::warning title=Run record::could not read the pull request's comments: {e}")
        if target:
            outcome = "ok"
            verdict = review_pr.review_verdict(target["body"])
            gate = _gate_of(target["body"])
        elif pr and pr.get("state") != "OPEN":
            outcome, gate = "ok", "closed"
            verdict = _findings_verdict(out)
            if verdict is None:
                print("::warning title=Run record::the review's verdict could not be read")
        else:
            reason = "cancelled" if args.job_status == "cancelled" else "publish-failed"
    else:
        reason = _failure_reason(args, numbers)

    ctx = {"repo": args.repo, "run_id": args.run_id, "attempt": args.attempt, "issue": ticket,
           "project": args.project, "login": args.login, "model": args.model,
           "budget": args.budget, "claude_code_version": args.claude_code_version}
    record = rr.build_record("review", ctx, numbers, outcome, reason, pr=pr_number,
                             head_sha=args.head_sha, round_=round_, verdict=verdict, gate=gate)
    line = rr.marker(record)
    (out / "run.json").write_text(json.dumps(record, indent=2) + "\n")
    try:
        if target:
            body = target["body"].rstrip("\n") + "\n" + line + "\n"
            gh.update_comment(args.repo, target["id"], write_comment(out, "run-comment.md", body))
        else:
            if outcome == "ok":
                said = f" {record['verdict']}" if record["verdict"] else ""
                text = (f"Review finished after this pull request closed:{said}. "
                        f"Nothing was changed. [run]({args.run_url})")
            else:
                text = f"Review failed: `{record['reason']}`. [run]({args.run_url})"
            gh.comment(args.repo, pr_number, write_comment(out, "run-comment.md", f"{text}\n{line}\n"))
    except GitHubError as e:
        print(f"::warning title=Run record::could not post the record: {e}")
    print(f"Run record: {record['outcome']}" + (f" ({record['reason']})" if record["reason"] else ""))
    return 0
