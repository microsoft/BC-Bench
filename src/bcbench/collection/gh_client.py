"""GitHub CLI client for fetching PR and commit data."""

import json
import subprocess
from typing import Any

from bcbench.exceptions import CollectionError
from bcbench.logger import get_logger

logger = get_logger(__name__)


class GHClient:
    def __init__(self, repo: str):
        self.repo = repo

    def get_pr_info(self, pr_number: int) -> dict[str, Any]:
        """Get pull request information using gh CLI."""
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
            check=False,
        )
        if result.returncode != 0:
            raise CollectionError(f"Failed to get PR info: {result.stderr}")
        return json.loads(result.stdout)

    def get_commit_info(self, commit: str) -> dict[str, Any]:
        """Get commit information using gh CLI."""
        result = subprocess.run(
            [
                "gh",
                "api",
                f"/repos/{self.repo}/commits/{commit}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise CollectionError(f"Failed to get commit info: {result.stderr}")
        return json.loads(result.stdout)

    def get_pr_diff(self, pr_number: int) -> str:
        """Get the diff for a pull request using gh CLI."""
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
            check=False,
        )
        if result.returncode != 0:
            raise CollectionError(f"Failed to get PR diff: {result.stderr}")
        return result.stdout

    def get_file_content(self, file_path: str, ref: str) -> str:
        """Get file content from GitHub at a specific ref using gh CLI."""
        result = subprocess.run(
            [
                "gh",
                "api",
                f"/repos/{self.repo}/contents/{file_path}",
                "-H",
                "Accept: application/vnd.github.raw+json",
                "-f",
                f"ref={ref}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise CollectionError(f"Failed to get file content for {file_path}: {result.stderr}")
        return result.stdout
