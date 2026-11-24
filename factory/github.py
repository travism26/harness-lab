"""The GitHub calls the factory makes, over the gh CLI with the App token in GH_TOKEN.

Only steps that run no agent use this. Tests pass a fake with the same methods.
"""

import json
import subprocess
from pathlib import Path
from urllib.parse import quote


class GitHubError(RuntimeError):
    pass


# Review runs on pull_request_target; CI runs on pull_request. A push to main
# shares neither, so a run for this head from `push` is not the PR's check.
_PR_EVENTS = ("pull_request", "pull_request_target")


def select_head_run(runs: list[dict], sha: str) -> dict | None:
    """The first run in `runs` whose head is sha and whose event is a pull request."""
    matching = [
        run
        for run in runs
        if run.get("headSha") == sha and run.get("event") in _PR_EVENTS
    ]
    return matching[0] if matching else None


class GitHub:
    def _gh(self, args: list[str]) -> str:
        r = subprocess.run(["gh", *args], capture_output=True, text=True)
        if r.returncode != 0:
            raise GitHubError(f"gh {' '.join(args[:3])} failed: {r.stderr.strip()}")
        return r.stdout

    def issue(self, repo: str, number: int) -> dict:
        return json.loads(
            self._gh(
                [
                    "issue",
                    "view",
                    str(number),
                    "-R",
                    repo,
                    "--json",
                    "number,title,body,state,author,labels,url",
                ]
            )
        )

    def open_issues_labelled(self, repo: str, label: str) -> list[int]:
        out = self._gh(
            [
                "issue",
                "list",
                "-R",
                repo,
                "--state",
                "open",
                "--label",
                label,
                "--limit",
                "100",
                "--json",
                "number",
            ]
        )
        return [i["number"] for i in json.loads(out)]

    def pr(self, repo: str, number: int) -> dict:
        return json.loads(
            self._gh(
                [
                    "pr",
                    "view",
                    str(number),
                    "-R",
                    repo,
                    "--json",
                    "number,title,body,state,isDraft,author,headRefName,"
                    "headRefOid,labels,url",
                ]
            )
        )

    def open_prs_for_branch(self, repo: str, branch: str) -> list[dict]:
        out = self._gh(
            [
                "pr",
                "list",
                "-R",
                repo,
                "--head",
                branch,
                "--state",
                "open",
                "--json",
                "number,headRefOid",
            ]
        )
        return json.loads(out)

    def pull_head_repo(self, repo: str, number: int) -> str:
        return self._gh(
            ["api", f"repos/{repo}/pulls/{number}", "--jq", ".head.repo.full_name"]
        ).strip()

    def workflow_run(self, repo: str, sha: str, workflow: str) -> dict | None:
        """The newest pull_request run of a workflow whose head is sha, if any."""
        out = self._gh(
            [
                "run",
                "list",
                "-R",
                repo,
                "--commit",
                sha,
                "--workflow",
                workflow,
                "--limit",
                "20",
                "--json",
                "databaseId,conclusion,status,event,headSha,url",
            ]
        )
        return select_head_run(json.loads(out), sha)

    def ci_conclusion(self, repo: str, sha: str) -> str | None:
        """The CI workflow's conclusion for this head, or None if it has not finished."""
        run = self.workflow_run(repo, sha, "ci.yml")
        conclusion = (run or {}).get("conclusion") or ""
        return conclusion or None

    def jobs(self, repo: str, run_id: int) -> list[dict]:
        out = self._gh(
            [
                "api",
                f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100",
                "--jq",
                ".jobs",
            ]
        )
        return json.loads(out)

    def job_log(self, repo: str, job_id: int) -> str:
        return self._gh(["api", f"repos/{repo}/actions/jobs/{job_id}/logs"])

    def _paged(self, path: str) -> list[dict]:
        """Every page of a list endpoint, flattened. A page that is an object (the runs
        endpoints wrap their list) comes back as one item."""
        out = self._gh(["api", "--paginate", "--slurp", path])
        return [
            item
            for page in json.loads(out)
            for item in (page if isinstance(page, list) else [page])
        ]

    def pr_comments(self, repo: str, number: int) -> list[dict]:
        return self._paged(f"repos/{repo}/issues/{number}/comments?per_page=100")

    def repo_comments(self, repo: str) -> list[dict]:
        """Every issue and pull request comment in the repo (the metrics report reads these)."""
        return self._paged(f"repos/{repo}/issues/comments?per_page=100")

    def label_events(self, repo: str, number: int) -> list[dict]:
        """The labeled and unlabeled events on a Ticket or pull request, as the timeline gives them."""
        return [
            e
            for e in self._paged(f"repos/{repo}/issues/{number}/timeline?per_page=100")
            if e.get("event") in ("labeled", "unlabeled")
        ]

    def pull_api(self, repo: str, number: int) -> dict:
        """The REST pull request (state, created_at, merged_at), not `gh pr view`'s shape."""
        return json.loads(self._gh(["api", f"repos/{repo}/pulls/{number}"]))

    def pull_commits(self, repo: str, number: int) -> list[dict]:
        return self._paged(f"repos/{repo}/pulls/{number}/commits?per_page=100")

    def branch_runs(self, repo: str, branch: str) -> list[dict]:
        """Every workflow run on a branch (CI, Review and Rework alike; the caller picks)."""
        pages = self._paged(
            f"repos/{repo}/actions/runs?branch={quote(branch, safe='')}&per_page=100"
        )
        return [run for page in pages for run in page.get("workflow_runs", [])]

    def workflow_runs(self, repo: str, workflow: str) -> list[dict]:
        """Every run of one workflow file, newest first."""
        pages = self._paged(
            f"repos/{repo}/actions/workflows/{workflow}.yml/runs?per_page=100"
        )
        return [run for page in pages for run in page.get("workflow_runs", [])]

    def attempt_run(self, repo: str, run_id: int, attempt: int) -> dict:
        return json.loads(
            self._gh(["api", f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}"])
        )

    def attempt_jobs(self, repo: str, run_id: int, attempt: int) -> list[dict]:
        out = self._gh(
            [
                "api",
                f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs"
                "?per_page=100",
                "--jq",
                ".jobs",
            ]
        )
        return json.loads(out)

    def run_artifacts(self, repo: str, run_id: int) -> list[dict]:
        out = self._gh(
            [
                "api",
                f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100",
                "--jq",
                ".artifacts",
            ]
        )
        return json.loads(out)

    def download_artifact(self, repo: str, run_id: int, name: str, dest: Path) -> None:
        self._gh(
            ["run", "download", str(run_id), "-R", repo, "-n", name, "-D", str(dest)]
        )

    def main_subjects(self, repo: str) -> list[str]:
        """The first line of every commit message on main, newest first."""
        messages = [
            (c.get("commit") or {}).get("message") or ""
            for c in self._paged(f"repos/{repo}/commits?sha=main&per_page=100")
        ]
        return [m.splitlines()[0] if m else "" for m in messages]

    def comment(self, repo: str, number: int, body_file: Path) -> int:
        # Issues and PRs share one number space; the issue endpoint takes both.
        out = self._gh(
            [
                "api",
                f"repos/{repo}/issues/{number}/comments",
                "-F",
                f"body=@{body_file}",
                "--jq",
                ".id",
            ]
        )
        return int(out.strip())

    def update_comment(self, repo: str, comment_id: int, body_file: Path) -> None:
        self._gh(
            [
                "api",
                "-X",
                "PATCH",
                f"repos/{repo}/issues/comments/{comment_id}",
                "-F",
                f"body=@{body_file}",
            ]
        )

    def add_labels(self, repo: str, number: int, labels: tuple) -> None:
        if labels:
            try:
                self._gh(
                    [
                        "api",
                        f"repos/{repo}/issues/{number}/labels",
                        *[x for label in labels for x in ("-f", f"labels[]={label}")],
                    ]
                )
            except GitHubError as e:
                raise GitHubError(
                    f"{e} (are the labels synced? "
                    "uv run python -m factory.sync_labels --apply)"
                ) from e

    def remove_labels(self, repo: str, number: int, labels: tuple) -> None:
        for label in labels:
            self._gh(
                [
                    "api",
                    "-X",
                    "DELETE",
                    f"repos/{repo}/issues/{number}/labels/{quote(label, safe='')}",
                ]
            )

    def create_draft_pr(
        self, repo: str, base: str, head: str, title: str, body_file: Path
    ) -> str:
        out = self._gh(
            [
                "pr",
                "create",
                "-R",
                repo,
                "--draft",
                "--base",
                base,
                "--head",
                head,
                "--title",
                title,
                "--body-file",
                str(body_file),
            ]
        )
        return out.strip().splitlines()[-1]

    def bot_user_id(self, app_slug: str) -> int:
        return int(self._gh(["api", f"users/{app_slug}[bot]", "--jq", ".id"]).strip())


def label_names(item: dict) -> list[str]:
    return [label["name"] for label in item.get("labels") or []]


def author(item: dict) -> str:
    return (item.get("author") or {}).get("login") or ""


def neutralize_comments(text: str) -> str:
    """Model text for a bot comment, unable to open or close an HTML comment. The factory
    reads its own hidden markers (`<!-- factory:... -->`) back from its comments, so text that
    is not the factory's own must not be able to form one."""
    # A zero-width space breaks the opener and closer without the entity, which a code span
    # would show as literal `&lt;`.
    return (text or "").replace("<!--", "<!\u200b--").replace("-->", "--\u200b>")


def write_comment(out: Path, name: str, body: str) -> Path:
    path = out / name
    path.write_text(body)
    return path
