import json
import subprocess
from typing import Any
from urllib.parse import quote


class GHClient:
    def __init__(self, repo: str):
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
            check=True,
        )
        return result.stdout

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
            check=True,
        )
        return result.stdout
