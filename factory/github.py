"""The GitHub calls the factory makes, over the gh CLI with the App token in GH_TOKEN.

Only steps that run no agent use this. Tests pass a fake with the same methods.
"""

import json
import subprocess
from pathlib import Path
from typing import List
from urllib.parse import quote


class GitHubError(RuntimeError):
    pass


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

    def pr_comments(self, repo: str, number: int) -> List[dict]:
        out = self._gh(["api", "--paginate", "--slurp",
                        f"repos/{repo}/issues/{number}/comments?per_page=100"])
        return [c for page in json.loads(out) for c in page]

    def comment(self, repo: str, number: int, body_file: Path) -> None:
        # Issues and PRs share one number space; the issue endpoint takes both.
        self._gh(["api", f"repos/{repo}/issues/{number}/comments", "-F", f"body=@{body_file}"])

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
