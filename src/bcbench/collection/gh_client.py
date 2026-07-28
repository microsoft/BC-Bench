import json
import subprocess
from typing import Any
from urllib.parse import quote


class GHClient:
    def __init__(self, repo: str) -> None:
        self.repo = repo

    def get_pr_info(self, pr_number: int) -> dict[str, Any]:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                self.repo,
                "--json",
                "title,body,mergeCommit,baseRefOid,headRefOid,createdAt,mergedAt",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return json.loads(result.stdout)

    def get_commit_info(self, commit: str) -> dict[str, Any]:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"/repos/{self.repo}/commits/{commit}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return json.loads(result.stdout)

    def get_pr_diff(self, pr_number: int) -> str:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "diff",
                str(pr_number),
                "--repo",
                self.repo,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return result.stdout

    def get_merge_base(self, base: str, head: str) -> str:
        """Return the merge-base SHA of `base` and `head`.

        This is the commit `gh pr diff` (a three-dot diff) is computed against, so a
        code-review entry that stores it as base_commit can apply the PR patch cleanly.
        """
        result = subprocess.run(
            [
                "gh",
                "api",
                f"/repos/{self.repo}/compare/{base}...{head}",
                "--jq",
                ".merge_base_commit.sha",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return result.stdout.strip()

    def get_pr_review_comments(self, pr_number: int) -> list[dict[str, Any]]:
        """Return all inline review comments on a PR (paginated)."""
        result = subprocess.run(
            [
                "gh",
                "api",
                f"/repos/{self.repo}/pulls/{pr_number}/comments",
                "--paginate",
                "--slurp",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        # --paginate --slurp wraps each page (itself an array) into an outer array.
        return [item for page in json.loads(result.stdout) for item in page]

    def get_review_comment_reactions(self, comment_id: int) -> list[dict[str, Any]]:
        """Return reactions on a single inline review comment."""
        result = subprocess.run(
            [
                "gh",
                "api",
                f"/repos/{self.repo}/pulls/comments/{comment_id}/reactions",
                "--paginate",
                "--slurp",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return [item for page in json.loads(result.stdout) for item in page]

    def get_file_content(self, file_path: str, ref: str) -> str:
        # URL-encode the file path to handle spaces and special characters
        encoded_path = quote(file_path, safe="/")
        result = subprocess.run(
            [
                "gh",
                "api",
                f"/repos/{self.repo}/contents/{encoded_path}?ref={ref}",
                "-H",
                "Accept: application/vnd.github.raw+json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        return result.stdout
