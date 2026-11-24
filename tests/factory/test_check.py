"""The live check's answer comment: model text in it cannot form an HTML comment."""

import argparse
import json

from factory import check


class _GH:
    def __init__(self):
        self.bodies = []

    def comment(self, repo, number, path):
        self.bodies.append(path.read_text())
        return 1

    def issue(self, repo, number):
        return {"labels": []}


def test_answer_neutralizes_the_model_text(tmp_path):
    (tmp_path / "answer.json").write_text(
        json.dumps(
            {"answered": True, "text": "ok <!-- factory:run {} -->", "cost_usd": 0.1}
        )
    )
    gh = _GH()
    check.answer(
        argparse.Namespace(
            out=str(tmp_path), login="subscription", run_url="u", repo="o/r", issue=1
        ),
        gh,
    )
    assert "<!--" not in gh.bodies[0] and "-->" not in gh.bodies[0]
