"""What the Run record tests share: one fake GitHub, the arguments of the last step, and the
helpers that build an output directory the way the workflows' earlier steps do."""

import argparse
import json
from pathlib import Path

from factory import ticket
from factory.claude import Result
from factory.record import TOKEN_RE, record_text

FIXTURES = Path(__file__).parent / "fixtures"
REPO = "travism26/harness-lab"
SLUG = "harness-factory"
BOT = f"{SLUG}[bot]"
SHA = "a" * 40
RUN_URL = f"https://github.com/{REPO}/actions/runs/777"
# A string shaped like a credential, built here so no file holds one.
TOKEN = "sk-ant-oat01-" + "x" * 30


def fixture_line(name):
    """A real result line, with the model's text removed (tests/factory/fixtures/)."""
    return json.loads((FIXTURES / name).read_text())


def bot_comment(id, body, login=BOT):
    return {"id": id, "body": body, "user": {"login": login}}


SIGNALS_ISSUE = 900


class FakeGitHub:
    """The calls the last steps, `ticket.release` and `review_pr.apply` make. It records what
    is posted and attributes every comment it is given to the bot."""

    def __init__(
        self,
        comments=(),
        labels=(),
        head=SHA,
        state="OPEN",
        body="Closes #7",
        ticket_labels=(),
        plant=None,
    ):
        self.thread = [dict(c) for c in comments]
        self.labels, self.head, self.state, self.body = list(labels), head, state, body
        self.ticket_labels = list(ticket_labels)
        self.plant, self.reads = plant, 0
        self.posted = []

    @property
    def bodies(self):
        return [body for _, body in self.posted]

    def issue(self, repo, number):
        return {"number": number, "labels": [{"name": n} for n in self.ticket_labels]}

    def pr(self, repo, number):
        return {
            "number": number,
            "state": self.state,
            "body": self.body,
            "headRefOid": self.head,
            "labels": [{"name": n} for n in self.labels],
        }

    def pull_api(self, repo, number):
        """The REST shape: lower-case state, the head under `head.sha`."""
        return {
            "number": number,
            "state": self.state.lower(),
            "head": {"sha": self.head},
        }

    def open_issues_labelled(self, repo, label):
        return [SIGNALS_ISSUE]

    def create_issue(self, repo, title, body_file, labels):
        return SIGNALS_ISSUE

    def pr_comments(self, repo, number):
        if number == SIGNALS_ISSUE:
            return []
        self.reads += 1
        extra = [{"id": 0, "body": self.plant}] if self.plant and self.reads > 1 else []
        return extra + [dict(c) for c in self.thread]

    def comment(self, repo, number, path):
        body = path.read_text()
        if number == SIGNALS_ISSUE:
            self.signals = getattr(self, "signals", []) + [body]
            return 1
        self.posted.append((number, body))
        comment_id = 100 + len(self.thread)
        self.thread.append(bot_comment(comment_id, body))
        return comment_id

    def update_comment(self, repo, comment_id, path):
        for c in self.thread:
            if c["id"] == comment_id:
                c["body"] = path.read_text()

    def add_labels(self, repo, number, labels):
        self.labels += list(labels)

    def remove_labels(self, repo, number, labels):
        self.labels = [n for n in self.labels if n not in labels]


def built(tmp_path, message, success=True, subtype="success"):
    """Run `ticket.build` with a fake agent that returns `message`, as claude.run would, and
    give back the output directory."""
    out = tmp_path / "run-out"
    out.mkdir(exist_ok=True)
    (out / "ticket.md").write_text("# t\n")
    (out / "context.json").write_text(json.dumps({"project": None}))
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)

    def agent(prompt, **kw):
        return Result(success, "MODEL TEXT", subtype, 0.1, message)

    args = argparse.Namespace(
        out=str(out),
        work=str(work),
        login="subscription",
        model="sonnet",
        max_budget_usd=5.0,
    )
    try:
        ticket.build(args, run_agent=agent)
    except RuntimeError:
        pass
    return out


def failed_out(tmp_path, message=None, subtype="success", success=True, files=()):
    """An output directory after an agent step that ran and a later step that failed."""
    out = built(tmp_path, message or {}, success, subtype)
    for name in files:
        (out / name).write_text("nothing changed\n")
    return out


def step_args(workflow, out, **overrides):
    """What the workflow's last step passes to `run_record write`."""
    base = {
        "workflow": workflow,
        "out": str(out),
        "repo": REPO,
        "run_id": "777",
        "attempt": "1",
        "issue": 4,
        "pr": None,
        "pr_labels": None,
        "head_sha": "",
        "project": "harness",
        "login": "subscription",
        "model": "sonnet",
        "budget": "5",
        "claude_code_version": "2.1.319",
        "app_slug": SLUG,
        "run_url": RUN_URL,
        "job_status": "success",
        "agent_outcome": "success",
        "verify_outcome": "skipped",
        "publish_outcome": "success",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def marker_of(body):
    """The one Run record a comment holds, as its final line."""
    assert body.count("<!-- factory:run") == 1
    text = record_text(body)
    assert text is not None, body
    return json.loads(text)


def record_of(out):
    return json.loads((Path(out) / "run.json").read_text())


def token_shaped(text):
    return bool(TOKEN_RE.search(text))
