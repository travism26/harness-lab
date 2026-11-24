"""The commit status `factory/review`: what a Review's outcome says at the merge box.

`status_for` is pure. `handoff` runs last in the `review` job and passes the outcome on as job
outputs; `resolve` runs in the `status` job, which holds `statuses: write` and no agent
(.github/workflows/review.yml, docs/adr/0012-review-verdict-is-a-commit-status-with-a-recorded-override.md).
Descriptions are written here, never taken from model text.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

CONTEXT = "factory/review"
VERDICTS = ("PASS", "BLOCKED")
REASONS = ("capped", "crashed", "timed-out", "no-verdict", "stale-head")

_REASON_TEXT = {
    "capped": "Review did not run: its daily run cap was reached",
    "crashed": "Review crashed before it reached a Verdict",
    "timed-out": "Review timed out before it reached a Verdict",
    "no-verdict": "Review finished without a Verdict",
    "stale-head": "The PR moved on while Review ran; the new head needs its own Review",
}


def status_for(outcome: Optional[str], reason: Optional[str]) -> Tuple[str, str]:
    """(state, description) for a Verdict (`PASS`, `BLOCKED`) or, with none, a reason code."""
    if outcome == "PASS":
        return "success", "Review passed"
    if outcome == "BLOCKED":
        return "failure", "Review blocked this head"
    if reason in _REASON_TEXT:
        return "error", _REASON_TEXT[reason]
    return "error", "Review ended in a state the factory does not recognise"


def pick(verdict: str, reason: str, review_result: str) -> Tuple[Optional[str], Optional[str]]:
    """The (outcome, reason) for the status job.

    A handed-over reason or Verdict wins. With neither, the reason comes from how the
    `review` job ended. GitHub documents `needs.<job>.result` as success, failure,
    cancelled or skipped and does not say what a timeout gives, so a timeout cannot be told
    from a crash: `timed-out` is only ever handed over, and the fallback is `crashed`.
    """
    if reason in REASONS:
        return None, reason
    if verdict in VERDICTS:
        return verdict, None
    if review_result == "success":
        return None, "no-verdict"
    return None, "crashed"


def _output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    line = f"{name}={value}"
    if path:
        with open(path, "a") as f:
            f.write(line + "\n")
    print(line)


def _read(path: Path) -> str:
    return path.read_text().strip() if path.is_file() else ""


def handoff(out: Path, capped: bool) -> int:
    """Write the job outputs `verdict`, `reason` and `comment-id`, each from its fixed set."""
    if capped:
        verdict, reason, comment_id = "", "capped", ""
    else:
        outcome = _read(out / "outcome.txt")
        comment_id = _read(out / "comment-id.txt")
        if not comment_id.isdigit():
            comment_id = ""
        verdict = ""
        for line in _read(out / "report.md").splitlines():
            if line.startswith("## Factory review: "):
                verdict = line[len("## Factory review: "):].strip()
                break
        if verdict not in VERDICTS:
            verdict = ""
        reason = "stale-head" if outcome == "stale" else ""
    _output("verdict", verdict)
    _output("reason", reason)
    _output("comment-id", comment_id)
    return 0


def resolve(verdict: str, reason: str, comment_id: str, review_result: str,
            repo: str, pr: str, run_url: str) -> int:
    """Print the status to set: `state`, `description` and `target-url` (the Review comment,
    else the run)."""
    outcome, why = pick(verdict, reason, review_result)
    state, description = status_for(outcome, why)
    target = run_url
    if comment_id.isdigit():
        target = f"https://github.com/{repo}/pull/{pr}#issuecomment-{comment_id}"
    _output("state", state)
    _output("description", description)
    _output("target-url", target)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="step", required=True)
    h = sub.add_parser("handoff")
    h.add_argument("--out", required=True)
    h.add_argument("--capped", default="false")
    r = sub.add_parser("resolve")
    r.add_argument("--verdict", default="")
    r.add_argument("--reason", default="")
    r.add_argument("--comment-id", default="")
    r.add_argument("--review-result", default="")
    r.add_argument("--repo", required=True)
    r.add_argument("--pr", required=True)
    r.add_argument("--run-url", required=True)
    args = parser.parse_args(argv)
    if args.step == "handoff":
        return handoff(Path(args.out), args.capped == "true")
    return resolve(args.verdict, args.reason, args.comment_id, args.review_result,
                   args.repo, args.pr, args.run_url)


if __name__ == "__main__":
    sys.exit(main())
