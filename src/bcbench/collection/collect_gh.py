"""Collection module for gathering dataset entries from GitHub PRs."""

from pathlib import Path
from typing import Any

import typer

from bcbench.collection.build_entry import save_problem_statement
from bcbench.collection.gh_client import GHClient
from bcbench.collection.patch_utils import extract_file_paths_from_patch, find_project_paths_from_diff, separate_patches
from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.exceptions import CollectionError
from bcbench.logger import get_logger
from bcbench.operations.test_operations import extract_tests_from_patch

logger = get_logger(__name__)
_config = get_config()

# Default BC environment setup version for GitHub-sourced entries
DEFAULT_ENVIRONMENT_VERSION = "26.0"


def collect_gh_entry(pr_number: int, output: Path, repo: str = "microsoft/BCApps") -> None:
    gh_client = GHClient(repo)

    try:
        logger.info("Collecting dataset entry for PR #%s from %s", pr_number, repo)

        pr_data: dict[str, Any] = gh_client.get_pr_info(pr_number)

        diff = gh_client.get_pr_diff(pr_number)

        patch, patch_fix, patch_test = separate_patches(diff, _config.file_patterns.test_project_identifiers)

        # Extract problem statement from PR
        title = pr_data.get("title", "")
        body = pr_data.get("body", "") or ""
        problem_statement = f"# {title}\n\n{body}" if body else f"# {title}"

        merge_commit = pr_data.get("mergeCommit", {})
        commit_id = merge_commit.get("oid", "") if merge_commit else pr_data.get("headRefOid", "")

        base_commit = pr_data.get("baseRefOid", "")

        if not commit_id or not base_commit:
            raise CollectionError("Unable to determine commit IDs from PR data")

        project_paths = find_project_paths_from_diff(patch)

        file_contents: dict[str, str] = {}
        for file_path in extract_file_paths_from_patch(patch_test):
            file_contents[file_path] = gh_client.get_file_content(file_path, commit_id)

        fail_to_pass = extract_tests_from_patch(patch_test, file_contents)

        instance_id = f"{repo.replace('/', '__')}-{pr_number}"

        save_problem_statement(instance_id=instance_id, problem_statement=problem_statement)

        entry = DatasetEntry(
            repo=repo,
            instance_id=instance_id,
            base_commit=base_commit,
            created_at=pr_data.get("createdAt", ""),
            patch=patch_fix,
            environment_setup_version=DEFAULT_ENVIRONMENT_VERSION,
            test_patch=patch_test,
            fail_to_pass=fail_to_pass,
            project_paths=project_paths,
        )

    except Exception as exc:
        logger.error("Failed to collect dataset entry: %s", exc)
        raise typer.Exit(code=1) from exc

    try:
        entry.save_to_file(output)
    except OSError as exc:
        logger.error("Failed to write dataset entry: %s", exc)
        raise typer.Exit(code=1) from exc

    logger.info(f"Saved dataset entry {entry.instance_id} to {output}")
