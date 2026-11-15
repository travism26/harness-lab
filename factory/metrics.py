"""The factory's metrics report: one row per factory Ticket and a totals row, as a markdown table.

Reads Run records (docs/factory/README.md, "Run records"), live through `gh` or offline from a
fixtures directory. Standard library and `gh` only; no model call.

  uv run python -m factory.metrics --repo travism26/harness-lab
  uv run python -m factory.metrics --fixtures tests/factory/fixtures/metrics

A fixtures directory holds one `ticket-<N>/` directory per Ticket. This step reads
`issue-comments.json` and `pr-comments.json` in each (the REST comments, as `gh api` prints
them). Later metrics read more files from the same directories, so a new column is a new file
and a new entry in COLUMNS.
"""
import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from factory.github import GitHub, GitHubError
from factory.run_record import MARKER_RE
from factory.switch_rule import is_factory_app

SCHEMA = 1
DEFAULT_APP_SLUG = "travism26-factory"
BACKFILL = Path(__file__).parent / "run-records-backfill.jsonl"
COMMENT_FILES = ("issue-comments.json", "pr-comments.json")
_MARKER = re.compile(r"<!-- factory:run (\{.*?\}) -->")
_TOKEN = re.compile(r"sk-ant-|sk-or-|\bsk-[A-Za-z0-9]{20,}|\bgh[pousr]_[A-Za-z0-9]{10,}"
                    r"|github_pat_|xox[abposr]-|eyJ[A-Za-z0-9_-]{10,}")


class MetricsError(RuntimeError):
    pass


# ---- reading ---------------------------------------------------------------------

def records_in(comments: List[dict], app_slug: str) -> List[dict]:
    """The Run records in the markers of the bot's own comments. A marker anywhere else is
    ignored. A marker whose JSON cannot be read is skipped with a warning."""
    found = []
    for comment in comments:
        body = comment.get("body")
        login = (comment.get("user") or {}).get("login") or ""
        if not isinstance(body, str) or not MARKER_RE.search(body) or not is_factory_app(login, app_slug):
            continue
        for text in _MARKER.findall(body):
            try:
                record = json.loads(text)
            except ValueError:
                print(f"warning: comment {comment.get('id')} holds a Run record that is not JSON",
                      file=sys.stderr)
                continue
            if isinstance(record, dict):
                found.append(record)
    return found


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
        if _TOKEN.search(path.read_text()):
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


# ---- grouping --------------------------------------------------------------------

@dataclass
class Ticket:
    issue: int
    records: List[dict] = field(default_factory=list)

    @property
    def implement(self) -> List[dict]:
        return [r for r in self.records if r.get("workflow") == "implement"]

    @property
    def pr(self) -> Optional[int]:
        prs = [r["pr"] for r in self.implement if r.get("pr")]
        return prs[-1] if prs else None

    @property
    def first_review(self) -> Optional[dict]:
        reviews = [r for r in self.records if r.get("workflow") == "review" and r.get("pr") == self.pr]
        return min(reviews, key=lambda r: (r.get("ts") or "", r.get("run_id") or 0)) if reviews else None


def tickets_from(records: List[dict]) -> List[Ticket]:
    """A factory Ticket is one with an Implement record. Its records are those naming its issue,
    or its pull request when the record names no issue."""
    issues = sorted({r["issue"] for r in records
                     if r.get("workflow") == "implement" and isinstance(r.get("issue"), int)})
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
    return f"${sum(costs):.2f} ({', '.join(logins)}, est.)"


def _time(tickets: List[Ticket]) -> str:
    times = [r["duration_ms"] for t in tickets for r in t.records
             if isinstance(r.get("duration_ms"), int)]
    if not times:
        return "n/a"
    seconds = round(sum(times) / 1000)
    return f"{seconds // 60}m {seconds % 60:02d}s"


def _drafts(tickets: List[Ticket]) -> List[Ticket]:
    return [t for t in tickets if t.pr]


def _first_pass(tickets: List[Ticket]) -> str:
    drafts = _drafts(tickets)
    return _rate(sum(1 for t in drafts if (t.first_review or {}).get("verdict") == "PASS"), len(drafts))


@dataclass
class Column:
    header: str
    cell: Callable[[Ticket], str]
    total: Callable[[List[Ticket]], str]


def _verdict(ticket: Ticket) -> str:
    if not ticket.pr:
        return "-"
    return (ticket.first_review or {}).get("verdict") or "none"


COLUMNS = [
    Column("Draft", lambda t: "yes" if t.pr else "no", lambda ts: _rate(len(_drafts(ts)), len(ts))),
    Column("First-pass review", _verdict, _first_pass),
    Column("Cost (estimate)", lambda t: _cost([t]), _cost),
    Column("Agent time", lambda t: _time([t]), _time),
]


def render(tickets: List[Ticket]) -> str:
    headers = ["Ticket"] + [c.header for c in COLUMNS]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for t in tickets:
        lines.append("| " + " | ".join([f"#{t.issue}"] + [c.cell(t) for c in COLUMNS]) + " |")
    lines.append("| " + " | ".join([f"Total ({len(tickets)})"] + [c.total(tickets) for c in COLUMNS]) + " |")
    return "\n".join(lines) + "\n"


# ---- entry point -----------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--repo", help="read live through gh, for example travism26/harness-lab")
    source.add_argument("--fixtures", help="read a fixtures directory instead of GitHub")
    parser.add_argument("--app-slug", default=DEFAULT_APP_SLUG,
                        help="the factory App whose comments carry records")
    parser.add_argument("--backfill", help=f"a backfill JSONL file; live runs read {BACKFILL} if it exists")
    args = parser.parse_args(argv)
    try:
        if args.fixtures:
            comments = read_fixtures(Path(args.fixtures))
            backfill = Path(args.backfill) if args.backfill else None
        else:
            comments = GitHub().repo_comments(args.repo)
            backfill = Path(args.backfill) if args.backfill else (BACKFILL if BACKFILL.is_file() else None)
        live = records_in(comments, args.app_slug)
        old = read_backfill(backfill) if backfill else []
        check_schema(live + old)
        sys.stdout.write(render(tickets_from(merge(live, old))))
    except (MetricsError, GitHubError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
