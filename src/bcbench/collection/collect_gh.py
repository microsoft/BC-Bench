"""Collection module for gathering dataset entries from GitHub PRs."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer

from bcbench.collection.gh_client import GHClient
from bcbench.collection.patch_utils import extract_file_paths_from_patch, find_project_paths_from_diff, separate_patches
from bcbench.config import get_config
from bcbench.dataset import BugFixEntry
from bcbench.exceptions import CollectionError
from bcbench.logger import get_logger
from bcbench.operations.test_operations import extract_tests_from_patch

logger = get_logger(__name__)
_config = get_config()

# Default BC environment setup version for GitHub-sourced entries
DEFAULT_ENVIRONMENT_VERSION = "26.0"

MIN_PROJECT_PATHS = 2


@dataclass
class ScreeningResult:
    pr_number: int
    repo: str
    passed: bool
    project_paths: list[str] = field(default_factory=list)
    has_fix_patch: bool = False
    has_test_patch: bool = False
    fail_to_pass_count: int = 0
    failures: list[str] = field(default_factory=list)


def _save_problem_statement(
    *,
    instance_id: str,
    problem_statement: str,
    problem_statement_dir: Path = _config.paths.problem_statement_dir,
    filename: str = _config.file_patterns.problem_statement_readme,
) -> None:
    output_dir = problem_statement_dir / instance_id
    output_dir.mkdir(parents=True, exist_ok=True)
    readme_path = output_dir / filename
    readme_path.write_text(problem_statement, encoding="utf-8")


def screen_gh_candidate(pr_number: int, repo: str = "microsoft/BCApps") -> ScreeningResult:
    gh_client = GHClient(repo)
    failures: list[str] = []

    try:
        pr_data: dict[str, Any] = gh_client.get_pr_info(pr_number)
        diff = gh_client.get_pr_diff(pr_number)
    except Exception as exc:
        raise CollectionError(f"Failed to fetch PR #{pr_number} from {repo}: {exc}") from exc

    try:
        _patch, patch_fix, patch_test = separate_patches(diff, _config.file_patterns.test_project_identifiers)
        project_paths = find_project_paths_from_diff(_patch)
    except CollectionError as exc:
        raise CollectionError(f"Failed to parse PR diff: {exc}") from exc

    has_fix_patch = bool(patch_fix.strip())
    has_test_patch = bool(patch_test.strip())

    if len(project_paths) < MIN_PROJECT_PATHS:
        failures.append(f"Fewer than {MIN_PROJECT_PATHS} project paths found (got {len(project_paths)})")

    if not has_fix_patch:
        failures.append("No fix changes found in diff")

    if not has_test_patch:
        failures.append("No test changes found in diff")

    fail_to_pass_count = 0
    if has_test_patch:
        merge_commit = pr_data.get("mergeCommit", {})
        commit_id = merge_commit.get("oid", "") if merge_commit else pr_data.get("headRefOid", "")
        file_contents: dict[str, str] = {}
        if commit_id:
            for file_path in extract_file_paths_from_patch(patch_test):
                try:
                    file_contents[file_path] = gh_client.get_file_content(file_path, commit_id)
                except Exception:
                    logger.debug("Could not fetch file content for %s", file_path)
        tests = extract_tests_from_patch(patch_test, file_contents)
        fail_to_pass_count = sum(len(t.functionName) for t in tests)
        if fail_to_pass_count == 0:
            failures.append("No testable functions found in test patch")

    return ScreeningResult(
        pr_number=pr_number,
        repo=repo,
        passed=len(failures) == 0,
        project_paths=project_paths,
        has_fix_patch=has_fix_patch,
        has_test_patch=has_test_patch,
        fail_to_pass_count=fail_to_pass_count,
        failures=failures,
    )


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

        _save_problem_statement(instance_id=instance_id, problem_statement=problem_statement)

        entry = BugFixEntry(
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
