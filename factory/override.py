"""The owner Override: a comment `Override: <reason>` sets the status `factory/review` to success.

`parse_override` is pure. `apply` reads the PR's state and head, sets the status and adds the
label. The workflow (.github/workflows/override.yml) holds no agent and no secret
(docs/adr/0012-review-verdict-is-a-commit-status-with-a-recorded-override.md). The reason stays
in the owner's comment: it is never copied into the status.
"""

import os
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from factory.github import GitHub, GitHubError
from factory.review_status import CONTEXT

LABEL = "review-override"
DESCRIPTION = "Overridden by the owner"
PREFIX = "Override:"

SetStatus = Callable[[str, str, str, str], None]


def parse_override(body: str) -> str | None:
    """The reason when the first line starts with `Override:` and a reason follows, else None."""
    lines = body.splitlines()
    if not lines or not lines[0].startswith(PREFIX):
        return None
    return lines[0][len(PREFIX) :].strip() or None


def apply(
    gh: Any, repo: str, pr: int, body: str, comment_url: str, set_status: SetStatus
) -> int:
    """Set `factory/review` to success on the PR's current head, if the comment is an Override
    and the PR is open, then label the PR. Only the number, state and head sha are used."""
    if parse_override(body) is None:
        print("not an Override: nothing to do")
        return 0
    info = gh.pr(repo, pr)
    if info.get("state") != "OPEN":
        print("the pull request is not open: nothing to do")
        return 0
    set_status(info["headRefOid"], "success", DESCRIPTION, comment_url)
    gh.add_labels(repo, pr, (LABEL,))
    print(f"Override set {CONTEXT} on {info['headRefOid']}")
    return 0


def _gh_status(repo: str) -> SetStatus:
    def set_status(sha: str, state: str, description: str, url: str) -> None:
        r = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repo}/statuses/{sha}",
                "-f",
                f"state={state}",
                "-f",
                f"context={CONTEXT}",
                "-f",
                f"description={description}",
                "-f",
                f"target_url={url}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0:
            raise GitHubError(f"setting the status failed: {r.stderr.strip()}")

    return set_status


def main() -> int:
    """Read the comment from the environment: BODY, REPO, PR, COMMENT_URL."""
    repo = os.environ["REPO"]
    return apply(
        GitHub(),
        repo,
        int(os.environ["PR"]),
        os.environ["BODY"],
        os.environ["COMMENT_URL"],
        _gh_status(repo),
    )


if __name__ == "__main__":
    sys.exit(main())
