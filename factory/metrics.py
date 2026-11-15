"""The factory's metrics report: one row per factory Ticket and a totals row, as a markdown table.

Reads Run records (docs/factory/README.md, "Run records"), live through `gh` or offline from a
fixtures directory. Standard library and `gh` only; no model call.

  uv run python -m factory.metrics --repo travism26/harness-lab
  uv run python -m factory.metrics --fixtures tests/factory/fixtures/metrics

A fixtures directory holds one `ticket-<N>/` directory per Ticket, with the REST JSON as `gh api`
prints it, cut down to the fields the report reads:

  issue-comments.json, pr-comments.json  comments, where Run records live
  issue-timeline.json, pr-timeline.json  label events (event, label.name, actor.login, created_at)
  pr.json                                state, created_at, merged_at
  pr-commits.json                        author.login, commit.author.name
  ci-runs.json                           workflow_runs (name, conclusion, created_at)

and, at the top, `main-subjects.json`: the commit subjects on main, newest first. A new column is a
new file and a new entry in COLUMNS.
"""
import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from factory.github import GitHub, GitHubError
from factory.record import BACKFILL_FILE, SCHEMA, TOKEN_RE, record_text
from factory.review_pr import HUMAN_LABEL, rework_round
from factory.switch_rule import default_app_slug, is_factory_app
from factory.ticket import START_LABEL, STARTED_PREFIX

COMMENT_FILES = ("issue-comments.json", "pr-comments.json")
# Tickets started before the rename (2026-11-08) used the old label.
START_LABELS = ("ready-for-agent", START_LABEL)
CI_WORKFLOW = "CI"
# The repo the committed fixtures were captured from, for the App slug when none is given.
FIXTURES_REPO = "travism26/harness-lab"


class MetricsError(RuntimeError):
    pass


# ---- reading ---------------------------------------------------------------------

def records_in(comments: List[dict], app_slug: str) -> List[dict]:
    """The Run records in the markers of the bot's own comments. Only a marker that is the whole
    final line of a comment counts; one anywhere else is somebody's quotation and is ignored. A
    marker whose JSON cannot be read is skipped with a warning."""
    found = []
    for comment in comments:
        login = (comment.get("user") or {}).get("login") or ""
        text = record_text(comment.get("body"))
        if text is None or not is_factory_app(login, app_slug):
            continue
        try:
            record = json.loads(text)
        except ValueError:
            print(f"warning: comment {comment.get('id')} holds a Run record that is not JSON",
                  file=sys.stderr)
            continue
        if isinstance(record, dict):
            found.append(record)
    return found


def claimed_issues(comments: List[dict], app_slug: str) -> List[int]:
    """The Tickets the factory bot claimed: the issue of each comment the bot wrote that starts
    with the claim's text. A comment names its issue in `issue_url`, which ends in `/issues/<N>`."""
    found = set()
    for comment in comments:
        login = (comment.get("user") or {}).get("login") or ""
        body = comment.get("body")
        if not (isinstance(body, str) and body.startswith(STARTED_PREFIX)
                and is_factory_app(login, app_slug)):
            continue
        number = re.search(r"/issues/(\d+)$", str(comment.get("issue_url") or ""))
        if number:
            found.add(int(number.group(1)))
    return sorted(found)


def read_backfill(path: Path) -> List[dict]:
    records = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            raise MetricsError(f"{path}: line {number} is not JSON")
        if isinstance(record, dict):
            records.append(record)
    return records


def read_fixtures(directory: Path) -> List[dict]:
    """Every comment under `directory`, after refusing a token-shaped string in any file."""
    if not directory.is_dir():
        raise MetricsError(f"{directory} is not a directory")
    comments = []
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        if TOKEN_RE.search(path.read_text()):
            raise MetricsError(f"{path} holds a token-shaped string; fixtures must not")
    for ticket_dir in sorted(p for p in directory.glob("ticket-*") if p.is_dir()):
        for name in COMMENT_FILES:
            path = ticket_dir / name
            if path.is_file():
                comments.extend(json.loads(path.read_text()))
    return comments


def check_schema(records: List[dict]) -> None:
    for record in records:
        if record.get("schema") != SCHEMA:
            raise MetricsError(f"a Run record has schema {record.get('schema')!r}; "
                               f"this report reads schema {SCHEMA} only")


def merge(*groups: List[dict]) -> List[dict]:
    """One record per run id and attempt; the first group to hold it wins."""
    seen, merged = set(), []
    for group in groups:
        for record in group:
            key = (record.get("run_id"), record.get("attempt"))
            if key not in seen:
                seen.add(key)
                merged.append(record)
    return merged


class FixtureSource:
    """Facts read from a fixtures directory (already refused if any file is token-shaped)."""

    def __init__(self, directory: Path):
        self.directory = directory

    def _json(self, path: Path, default):
        return json.loads(path.read_text()) if path.is_file() else default

    def facts(self, issue: int, pr: int, app_slug: str) -> "Facts":
        d = self.directory / f"ticket-{issue}"
        runs = self._json(d / "ci-runs.json", {})
        return Facts(app_slug,
                     events=(self._json(d / "issue-timeline.json", [])
                             + self._json(d / "pr-timeline.json", [])),
                     pr=self._json(d / "pr.json", {}),
                     commits=self._json(d / "pr-commits.json", []),
                     runs=runs.get("workflow_runs", []))

    def main_subjects(self) -> List[str]:
        return self._json(self.directory / "main-subjects.json", [])


class LiveSource:
    """Facts read through gh. Per draft: two timelines, the pull request, its commits and the runs
    on its branch. Commit subjects on main are read through the API, not a local clone: a clone may
    be stale or absent, and the API answers for the repo named by --repo."""

    def __init__(self, gh, repo: str):
        self.gh, self.repo = gh, repo

    def facts(self, issue: int, pr: int, app_slug: str) -> "Facts":
        return Facts(app_slug,
                     events=(self.gh.label_events(self.repo, issue)
                             + self.gh.label_events(self.repo, pr)),
                     pr=self.gh.pull_api(self.repo, pr),
                     commits=self.gh.pull_commits(self.repo, pr),
                     runs=self.gh.branch_runs(self.repo, f"factory/issue-{issue}"))

    def main_subjects(self) -> List[str]:
        return self.gh.main_subjects(self.repo)


def attach_facts(tickets: List["Ticket"], source, app_slug: str) -> None:
    """Give every Ticket that opened a draft its facts."""
    subjects = source.main_subjects() if any(t.pr for t in tickets) else []
    for ticket in tickets:
        if ticket.pr:
            ticket.facts = source.facts(ticket.issue, ticket.pr, app_slug)
            ticket.facts.main_subjects = subjects


# ---- grouping --------------------------------------------------------------------

@dataclass
class Facts:
    """What the labels, the pull request, its commits and CI say about one Ticket's draft."""
    app_slug: str
    events: List[dict] = field(default_factory=list)
    pr: dict = field(default_factory=dict)
    commits: List[dict] = field(default_factory=list)
    runs: List[dict] = field(default_factory=list)
    main_subjects: List[str] = field(default_factory=list)

    def by_bot(self, login: str) -> bool:
        return is_factory_app(login or "", self.app_slug)

    def bot_added(self) -> List[str]:
        """The labels the factory bot added. A label anyone else added does not count."""
        return [e["label"]["name"] for e in self.events
                if e.get("event") == "labeled" and self.by_bot((e.get("actor") or {}).get("login"))]

    @property
    def rework_rounds(self) -> int:
        return rework_round(self.bot_added())

    @property
    def owner_commits(self) -> int:
        """Commits on the factory branch the bot did not author."""
        return sum(1 for c in self.commits
                   if not self.by_bot((c.get("author") or {}).get("login")
                                      or ((c.get("commit") or {}).get("author") or {}).get("name")))

    @property
    def escalated(self) -> bool:
        """The factory bot sent the pull request to a human (a label anyone else added is not
        the factory's escalation)."""
        return HUMAN_LABEL in self.bot_added()

    @property
    def human_labelled(self) -> bool:
        """Anyone, the bot or a person, put the human label on the pull request or its Ticket."""
        return any(e.get("event") == "labeled" and (e.get("label") or {}).get("name") == HUMAN_LABEL
                   for e in self.events)

    @property
    def state(self) -> str:
        """merged, closed (unmerged) or open."""
        if self.pr.get("merged_at"):
            return "merged"
        return "closed" if self.pr.get("state") == "closed" else "open"

    @property
    def first_ci(self) -> Optional[str]:
        """The conclusion of the first CI run on the branch (Review and the CI gate are not CI)."""
        ci = sorted((r for r in self.runs if r.get("name") == CI_WORKFLOW),
                    key=lambda r: r.get("created_at") or "")
        return (ci[0].get("conclusion") or "pending") if ci else None

    @property
    def start_to_draft(self) -> Optional[int]:
        """Seconds from the bot removing a start label (the last time, at or before the draft)
        to the pull request's creation."""
        created = _when(self.pr.get("created_at"))
        removed = [_when(e.get("created_at")) for e in self.events
                   if e.get("event") == "unlabeled"
                   and (e.get("label") or {}).get("name") in START_LABELS
                   and self.by_bot((e.get("actor") or {}).get("login"))]
        before = [t for t in removed if t and created and t <= created]
        return int((created - max(before)).total_seconds()) if before else None

    @property
    def reverts(self) -> int:
        """Later commit subjects on main that start with Revert and name the pull request."""
        number = self.pr.get("number")
        if self.state != "merged" or not number:
            return 0
        named = re.compile(rf"#{number}(?!\d)")
        return sum(1 for subject in self.main_subjects
                   if subject.startswith("Revert") and named.search(subject))

    @property
    def untouched(self) -> bool:
        """Merged with no commit from anyone but the bot, and nobody put the human label on."""
        return self.state == "merged" and not self.owner_commits and not self.human_labelled


@dataclass
class Ticket:
    issue: int
    records: List[dict] = field(default_factory=list)
    facts: Optional[Facts] = None

    @property
    def implement(self) -> List[dict]:
        return [r for r in self.records if r.get("workflow") == "implement"]

    @property
    def pr(self) -> Optional[int]:
        prs = [r["pr"] for r in self.implement if r.get("pr")]
        return prs[-1] if prs else None

    @property
    def first_review(self) -> Optional[dict]:
        reviews = [r for r in self.records
                   if r.get("workflow") == "review" and r.get("pr") == self.pr]
        if not reviews:
            return None
        return min(reviews, key=lambda r: (r.get("ts") or "", r.get("run_id") or 0))


def tickets_from(records: List[dict], claimed: List[int] = ()) -> List[Ticket]:
    """A factory Ticket is one the factory bot claimed (`claimed`) or one an Implement record
    names, since a record proves a claim. Its records are those naming its issue, or its pull
    request when the record names no issue."""
    issues = sorted({r["issue"] for r in records
                     if r.get("workflow") == "implement" and isinstance(r.get("issue"), int)}
                    | set(claimed))
    tickets = [Ticket(i, [r for r in records if r.get("issue") == i]) for i in issues]
    for ticket in tickets:
        ticket.records += [r for r in records if r.get("issue") is None and r.get("pr")
                           and r["pr"] == ticket.pr]
    return tickets


# ---- the table -------------------------------------------------------------------

def _rate(n: int, d: int) -> str:
    return f"{n}/{d} ({round(100 * n / d)}%)" if d else "n/a"


def _cost(tickets: List[Ticket]) -> str:
    records = [r for t in tickets for r in t.records]
    costs = [r["cost_usd"] for r in records if isinstance(r.get("cost_usd"), (int, float))]
    if not costs:
        return "n/a"
    logins = sorted({r["login"] for r in records if r.get("login")})
    return f"${sum(costs):.2f} ({', '.join([*logins, 'est.'])})"


def _clock(seconds: int) -> str:
    return f"{seconds // 60}m {seconds % 60:02d}s"


def _time(tickets: List[Ticket]) -> str:
    times = [r["duration_ms"] for t in tickets for r in t.records
             if isinstance(r.get("duration_ms"), int)]
    return _clock(round(sum(times) / 1000)) if times else "n/a"


def _drafts(tickets: List[Ticket]) -> List[Ticket]:
    return [t for t in tickets if t.pr]


def _first_pass(tickets: List[Ticket]) -> str:
    drafts = _drafts(tickets)
    passed = sum(1 for t in drafts if (t.first_review or {}).get("verdict") == "PASS")
    return _rate(passed, len(drafts))


@dataclass
class Column:
    header: str
    cell: Callable[[Ticket], str]
    total: Callable[[List[Ticket]], str]


def _verdict(ticket: Ticket) -> str:
    if not ticket.pr:
        return "-"
    return (ticket.first_review or {}).get("verdict") or "none"


def _when(text: Optional[str]) -> Optional[datetime]:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ") if text else None


def _wait_total(facts: List[Facts]) -> str:
    waits = [f.start_to_draft for f in facts if f.start_to_draft is not None]
    return _clock(round(statistics.median(waits))) if waits else "n/a"


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def _facts_cell(render: Callable[[Facts], str]) -> Callable[[Ticket], str]:
    """A cell read from the Ticket's facts; `-` for a Ticket with no draft or no facts."""
    return lambda t: render(t.facts) if t.pr and t.facts else "-"


def _facts_total(render: Callable[[List[Facts]], str]) -> Callable[[List[Ticket]], str]:
    return lambda ts: render([t.facts for t in _drafts(ts) if t.facts])


COLUMNS = [
    Column("Draft", lambda t: "yes" if t.pr else "no", lambda ts: _rate(len(_drafts(ts)), len(ts))),
    Column("First-pass review", _verdict, _first_pass),
    Column("Cost (estimate)", lambda t: _cost([t]), _cost),
    Column("Agent time", lambda t: _time([t]), _time),
    Column("Rework rounds", _facts_cell(lambda f: str(f.rework_rounds)),
           _facts_total(lambda fs: str(sum(f.rework_rounds for f in fs)))),
    Column("Owner commits", _facts_cell(lambda f: str(f.owner_commits)),
           _facts_total(lambda fs: str(sum(f.owner_commits for f in fs)))),
    Column("Human escalation", _facts_cell(lambda f: _yes(f.escalated)),
           _facts_total(lambda fs: _rate(sum(f.escalated for f in fs), len(fs)))),
    Column("CI on first push",
           _facts_cell(lambda f: {"success": "yes", None: "none",
                                  "pending": "pending"}.get(f.first_ci, "no")),
           _facts_total(lambda fs: _rate(sum(f.first_ci == "success" for f in fs), len(fs)))),
    Column("Start label to draft",
           _facts_cell(lambda f: ("n/a" if f.start_to_draft is None
                                  else _clock(f.start_to_draft))),
           _facts_total(_wait_total)),
    Column("Merge", _facts_cell(lambda f: f.state),
           _facts_total(lambda fs: _rate(sum(f.state == "merged" for f in fs),
                                         sum(f.state != "open" for f in fs)))),
    Column("Untouched merge", _facts_cell(lambda f: _yes(f.untouched)),
           _facts_total(lambda fs: _rate(sum(f.untouched for f in fs), len(fs)))),
    Column("Post-merge reverts", _facts_cell(lambda f: str(f.reverts)),
           _facts_total(lambda fs: str(sum(f.reverts for f in fs)))),
]


def render(tickets: List[Ticket]) -> str:
    headers = ["Ticket"] + [c.header for c in COLUMNS]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for t in tickets:
        lines.append("| " + " | ".join([f"#{t.issue}"] + [c.cell(t) for c in COLUMNS]) + " |")
    totals = [f"Total ({len(tickets)})"] + [c.total(tickets) for c in COLUMNS]
    lines.append("| " + " | ".join(totals) + " |")
    return "\n".join(lines) + "\n"


# ---- entry point -----------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo", help="read live through gh, for example travism26/harness-lab")
    source.add_argument("--fixtures", help="read a fixtures directory instead of GitHub")
    parser.add_argument("--app-slug", default=None,
                        help="the factory App whose comments carry records; "
                             "default OWNER-factory, from --repo")
    parser.add_argument("--backfill",
                        help=f"a backfill JSONL file; live runs read {BACKFILL_FILE} if it exists")
    args = parser.parse_args(argv)
    app_slug = args.app_slug or default_app_slug(args.repo or FIXTURES_REPO)
    try:
        if args.fixtures:
            comments = read_fixtures(Path(args.fixtures))
            source = FixtureSource(Path(args.fixtures))
            backfill = Path(args.backfill) if args.backfill else None
        else:
            gh = GitHub()
            comments = gh.repo_comments(args.repo)
            source = LiveSource(gh, args.repo)
            default = BACKFILL_FILE if BACKFILL_FILE.is_file() else None
            backfill = Path(args.backfill) if args.backfill else default
        live = records_in(comments, app_slug)
        old = read_backfill(backfill) if backfill else []
        check_schema(live + old)
        tickets = tickets_from(merge(live, old), claimed_issues(comments, app_slug))
        attach_facts(tickets, source, app_slug)
        sys.stdout.write(render(tickets))
    except (MetricsError, GitHubError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
