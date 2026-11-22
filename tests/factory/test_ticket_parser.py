"""Ticket commands are checked through the real argument parser.

Ticket #18 hid behind hand-built arguments: the rework-refusal path read `args.run_url`
while the `revise` parser had no `--run-url`, so a real refusal crashed before it could
comment. These tests drive `factory/ticket.py` through `ticket.main([...])` with the flags
`.github/workflows/implement.yml` and `.github/workflows/rework.yml` pass, and audit the
handlers and the hand-built arguments in `tests/factory/test_ticket.py` against the parser.
"""
import argparse
import ast
from pathlib import Path

import pytest

from factory import ticket
from tests.factory.test_ticket import REPO, FakeGitHub, _issue, _pr, _root

ROOT = Path(__file__).resolve().parents[2]
RUN = "https://example.test/actions/runs/1"


def test_claim_refusal_through_the_parser_comments_with_the_run_url(tmp_path, monkeypatch, capsys):
    _root(tmp_path, executable=False)
    monkeypatch.chdir(tmp_path / "root")  # the workflow passes no --root: the default "."
    gh = FakeGitHub(issue=_issue(labels=("ready-for-factory", "project:harness")))
    monkeypatch.setattr(ticket, "GitHub", lambda: gh)
    code = ticket.main([
        "claim", "--repo", REPO, "--issue", "4", "--out", str(tmp_path / "out"),
        "--login", "subscription", "--app-slug", "harness-factory", "--run-url", RUN])
    assert code == 1
    assert len(gh.posted) == 1 and gh.posted[0][0] == 4
    assert "did not start" in gh.posted[0][1] and RUN in gh.posted[0][1]
    assert "AttributeError" not in capsys.readouterr().out


def test_revise_refusal_through_the_parser_with_the_workflow_flags(tmp_path, monkeypatch, capsys):
    _root(tmp_path, executable=False)
    monkeypatch.chdir(tmp_path / "root")  # the workflow passes no --root: the default "."
    gh = FakeGitHub(issue=_issue(labels=("project:harness",)), pr=_pr())
    monkeypatch.setattr(ticket, "GitHub", lambda: gh)
    code = ticket.main([
        "revise", "--repo", REPO, "--pr", "9", "--out", str(tmp_path / "out"),
        "--login", "subscription", "--app-slug", "harness-factory", "--run-url", RUN])
    assert code == 1
    assert len(gh.posted) == 1 and gh.posted[0][0] == 4
    assert "did not start a rework round" in gh.posted[0][1] and RUN in gh.posted[0][1]
    assert "AttributeError" not in capsys.readouterr().out


def test_release_through_the_parser_comments_with_the_run_url(tmp_path, monkeypatch):
    gh = FakeGitHub(issue=_issue(labels=("in-progress",)))
    monkeypatch.setattr(ticket, "GitHub", lambda: gh)
    code = ticket.main(["release", "--repo", REPO, "--issue", "4",
                        "--out", str(tmp_path / "out"), "--run-url", RUN])
    assert code == 0
    assert RUN in gh.posted[0][1] and gh.removed == ["in-progress"]


class _Captured(Exception):
    pass


def _parser_dests(monkeypatch):
    """The dests the real parser defines for each subcommand, captured from `ticket.main`."""
    seen = []

    def capture(self, *a, **kw):
        seen.append(self)
        raise _Captured

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", capture)
    with pytest.raises(_Captured):
        ticket.main([])
    (action,) = [a for a in seen[0]._actions if isinstance(a, argparse._SubParsersAction)]
    return {name: {a.dest for a in p._actions if a.dest != "help"}
            for name, p in action.choices.items()}


def _functions(tree):
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _step_handlers(main_fn):
    (steps,) = [n.value for n in ast.walk(main_fn)
                if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "steps" for t in n.targets)]
    return {k.value: v.id for k, v in zip(steps.keys, steps.values)}


def test_every_flag_a_handler_reads_is_defined_by_its_parser(monkeypatch):
    dests = _parser_dests(monkeypatch)
    funcs = _functions(ast.parse((ROOT / "factory" / "ticket.py").read_text()))
    handlers = _step_handlers(funcs["main"])
    assert set(handlers) == set(dests)
    for step, name in handlers.items():
        fn = funcs[name]
        attr_uses = {id(n.value) for n in ast.walk(fn)
                     if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "args"}
        other = [n for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "args"
                 and isinstance(n.ctx, ast.Load) and id(n) not in attr_uses]
        assert not other, (f"`{step}` uses `args` other than as args.<attr> (line {other[0].lineno}); "
                           "the audit cannot follow it")
        read = {n.attr for n in ast.walk(fn)
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "args"}
        assert read <= dests[step], f"`{step}` reads args.{sorted(read - dests[step])} but its parser lacks it"


def test_hand_built_arguments_carry_only_flags_the_parser_defines(monkeypatch):
    union = set().union(*_parser_dests(monkeypatch).values())
    tree = ast.parse((ROOT / "tests" / "factory" / "test_ticket.py").read_text())
    def callee(n):
        return n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")

    keys = set()
    # `_args` builds its base with dict(...); call sites override with keywords.
    for n in ast.walk(_functions(tree)["_args"]):
        if isinstance(n, ast.Call) and callee(n) == "dict":
            keys |= {k.arg for k in n.keywords if k.arg}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and callee(n) in ("_args", "Namespace"):
            keys |= {k.arg for k in n.keywords if k.arg}
    assert {"run_url", "app_slug"} <= keys, "the audit no longer sees the hand-built arguments"
    assert keys <= union, f"hand-built args carry {sorted(keys - union)}, which no parser defines"
