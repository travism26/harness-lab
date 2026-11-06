"""The live check: the factory answers the `factory-check` label (docs/factory/setup.md).

.github/workflows/factory-check.yml runs it in two steps:

  ask     (Claude login, no GitHub token) asks Claude Code for a one-line reply,
          with every tool denied and a few cents of budget, and writes the
          answer into --out.
  answer  (App token) posts the answer on the issue and removes the label.

Usage:
  uv run python -m factory.check ask --out check-out --login L
  uv run python -m factory.check answer --repo O/R --issue N --out check-out --login L --run-url URL
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from factory import claude
from factory.github import GitHub, GitHubError, label_names, write_comment
from factory.switch_rule import LOGINS

LABEL = "factory-check"
EXPECTED = "factory ok"
PROMPT = f"Reply with exactly these two words and nothing else: {EXPECTED}"
BUDGET_USD = 0.10
DENIED_TOOLS = ["Bash", "Edit", "Write", "NotebookEdit", "Read", "Grep", "Glob",
                "WebFetch", "WebSearch", "Agent", "Task"]


def ask(args, run_agent=claude.run) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        result = run_agent(PROMPT, login=args.login, model="haiku", max_budget_usd=BUDGET_USD,
                           cwd=os.getcwd(), transcript=out / "agent.jsonl",
                           disallowed_tools=DENIED_TOOLS)
    finally:
        claude.scrub(out, claude.secret_values(os.environ))
    answered = result.success and EXPECTED in result.text.lower()
    (out / "answer.json").write_text(json.dumps(
        {"answered": answered, "text": result.text[:200], "cost_usd": result.cost_usd}) + "\n")
    if not answered:
        raise RuntimeError(f"Claude Code did not answer: {result.text[:300]}")
    print(f"Claude Code answered on the {args.login} login: {result.text.strip()!r}")
    return 0


def answer(args, gh: Optional[GitHub] = None) -> int:
    gh = gh or GitHub()
    out = Path(args.out)
    reply = json.loads((out / "answer.json").read_text())
    body = (f"Factory check: the factory answered as its GitHub App, and Claude Code replied "
            f"`{reply['text'].strip()}` on the `{args.login}` login "
            f"(${reply['cost_usd']:.4f}). [Run]({args.run_url})\n")
    gh.comment(args.repo, args.issue, write_comment(out, "answer.md", body))
    if LABEL in label_names(gh.issue(args.repo, args.issue)):
        gh.remove_labels(args.repo, args.issue, (LABEL,))
    print(body)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="step", required=True)
    a = sub.add_parser("ask")
    a.add_argument("--out", required=True)
    a.add_argument("--login", choices=LOGINS, required=True)
    n = sub.add_parser("answer")
    n.add_argument("--repo", required=True)
    n.add_argument("--issue", type=int, required=True)
    n.add_argument("--out", required=True)
    n.add_argument("--login", choices=LOGINS, required=True)
    n.add_argument("--run-url", required=True)
    args = parser.parse_args(argv)
    try:
        return {"ask": ask, "answer": answer}[args.step](args)
    except (RuntimeError, GitHubError, claude.ConfigError) as e:
        print(f"::error title=Factory check {args.step} failed::{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
