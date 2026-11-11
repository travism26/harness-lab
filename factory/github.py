"""The GitHub calls the factory makes, over the gh CLI with the App token in GH_TOKEN.

Only steps that run no agent use this. Tests pass a fake with the same methods.
"""

import json
import subprocess
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote


class GitHubError(RuntimeError):
    pass


# Review runs on pull_request_target; CI runs on pull_request. A push to main
# shares neither, so a run for this head from `push` is not the PR's check.
_PR_EVENTS = ("pull_request", "pull_request_target")


def select_head_run(runs: List[dict], sha: str) -> Optional[dict]:
    """The first run in `runs` whose head is sha and whose event is a pull request."""
    matching = [run for run in runs
                if run.get("headSha") == sha and run.get("event") in _PR_EVENTS]
    return matching[0] if matching else None


class GitHub:
    def _gh(self, args: List[str]) -> str:
        r = subprocess.run(["gh", *args], capture_output=True, text=True)
        if r.returncode != 0:
            raise GitHubError(f"gh {' '.join(args[:3])} failed: {r.stderr.strip()}")
        return r.stdout

    def issue(self, repo: str, number: int) -> dict:
        return json.loads(self._gh(["issue", "view", str(number), "-R", repo, "--json",
                                    "number,title,body,state,author,labels,url"]))

    def open_issues_labelled(self, repo: str, label: str) -> List[int]:
        out = self._gh(["issue", "list", "-R", repo, "--state", "open", "--label", label,
                        "--limit", "100", "--json", "number"])
        return [i["number"] for i in json.loads(out)]

    def pr(self, repo: str, number: int) -> dict:
        return json.loads(self._gh(["pr", "view", str(number), "-R", repo, "--json",
                                    "number,title,body,state,isDraft,author,headRefName,"
                                    "headRefOid,labels,url"]))

    def open_prs_for_branch(self, repo: str, branch: str) -> List[dict]:
        out = self._gh(["pr", "list", "-R", repo, "--head", branch, "--state", "open",
                        "--json", "number,headRefOid,isCrossRepository"])
        return json.loads(out)

    def pull_head_repo(self, repo: str, number: int) -> str:
        return self._gh(["api", f"repos/{repo}/pulls/{number}",
                         "--jq", ".head.repo.full_name"]).strip()

    def workflow_run(self, repo: str, sha: str, workflow: str) -> Optional[dict]:
        """The newest pull_request run of a workflow whose head is sha, if any."""
        out = self._gh(["run", "list", "-R", repo, "--commit", sha, "--workflow", workflow,
                        "--limit", "20",
                        "--json", "databaseId,conclusion,status,event,headSha,url"])
        return select_head_run(json.loads(out), sha)

    def ci_conclusion(self, repo: str, sha: str) -> Optional[str]:
        """The CI workflow's conclusion for this head, or None if it has not finished."""
        run = self.workflow_run(repo, sha, "ci.yml")
        conclusion = (run or {}).get("conclusion") or ""
        return conclusion or None

    def jobs(self, repo: str, run_id: int) -> List[dict]:
        out = self._gh(["api", f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100",
                        "--jq", ".jobs"])
        return json.loads(out)

    def job_log(self, repo: str, job_id: int) -> str:
        return self._gh(["api", f"repos/{repo}/actions/jobs/{job_id}/logs"])

    def pr_comments(self, repo: str, number: int) -> List[dict]:
        out = self._gh(["api", "--paginate", "--slurp",
                        f"repos/{repo}/issues/{number}/comments?per_page=100"])
        return [c for page in json.loads(out) for c in page]

    def comment(self, repo: str, number: int, body_file: Path) -> int:
        # Issues and PRs share one number space; the issue endpoint takes both.
        out = self._gh(["api", f"repos/{repo}/issues/{number}/comments",
                        "-F", f"body=@{body_file}", "--jq", ".id"])
        return int(out.strip())

    def update_comment(self, repo: str, comment_id: int, body_file: Path) -> None:
        self._gh(["api", "-X", "PATCH", f"repos/{repo}/issues/comments/{comment_id}",
                  "-F", f"body=@{body_file}"])

    def add_labels(self, repo: str, number: int, labels: tuple) -> None:
        if labels:
            try:
                self._gh(["api", f"repos/{repo}/issues/{number}/labels",
                          *[x for label in labels for x in ("-f", f"labels[]={label}")]])
            except GitHubError as e:
                raise GitHubError(f"{e} (are the labels synced? "
                                  "uv run python -m factory.sync_labels --apply)") from e

    def remove_labels(self, repo: str, number: int, labels: tuple) -> None:
        for label in labels:
            self._gh(["api", "-X", "DELETE", f"repos/{repo}/issues/{number}/labels/{quote(label, safe='')}"])

    def create_draft_pr(self, repo: str, base: str, head: str, title: str,
                        body_file: Path) -> str:
        out = self._gh(["pr", "create", "-R", repo, "--draft", "--base", base, "--head", head,
                        "--title", title, "--body-file", str(body_file)])
        return out.strip().splitlines()[-1]

    def bot_user_id(self, app_slug: str) -> int:
        return int(self._gh(["api", f"users/{app_slug}[bot]", "--jq", ".id"]).strip())


def label_names(item: dict) -> List[str]:
    return [label["name"] for label in item.get("labels") or []]


def author(item: dict) -> str:
    return (item.get("author") or {}).get("login") or ""


def write_comment(out: Path, name: str, body: str) -> Path:
    path = out / name
    path.write_text(body)
    return path
