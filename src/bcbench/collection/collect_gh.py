"""Collection module for gathering dataset entries from GitHub PRs."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from bcbench.collection.gh_client import GHClient
from bcbench.collection.patch_utils import extract_file_paths_from_patch, find_project_paths_from_diff, separate_patches
from bcbench.config import get_config
from bcbench.dataset import BugFixEntry
from bcbench.exceptions import CollectionError, NoTestsExtractedError
from bcbench.logger import get_logger
from bcbench.operations import extract_tests_from_patch

logger = get_logger(__name__)
_config = get_config()

MIN_PROJECT_PATHS = 2


@dataclass
class ScreeningResult:
    pr_number: int
    repo: str
    passed: bool
    reason: str | None = None


def _save_problem_statement(
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
    """Run automated screening on a PR; stop and return on first failure.

    Read-only: no entry is written and no problem statement is saved.

    Screening is preliminary. A passing result still requires manual review for things we can't easily automate
    (e.g. whether the test has dependency on the fix, whether the bug context is sufficient).
    """
    gh_client = GHClient(repo)

    def fail(reason: str) -> ScreeningResult:
        return ScreeningResult(pr_number=pr_number, repo=repo, passed=False, reason=reason)

    try:
        pr_data: dict[str, Any] = gh_client.get_pr_info(pr_number)
        diff = gh_client.get_pr_diff(pr_number)
    except Exception as exc:
        raise CollectionError(f"Failed to fetch PR #{pr_number} from {repo}: {exc}") from exc

    try:
        patch, patch_fix, patch_test = separate_patches(diff, _config.file_patterns.test_project_identifiers)
        project_paths = find_project_paths_from_diff(patch)
    except CollectionError as exc:
        raise CollectionError(f"Failed to parse PR diff: {exc}") from exc

    if len(project_paths) < MIN_PROJECT_PATHS:
        return fail(f"Fewer than {MIN_PROJECT_PATHS} project paths found (got {len(project_paths)})")

    if not patch_fix.strip():
        return fail("No fix changes found in diff")

    if not patch_test.strip():
        return fail("No test changes found in diff")

    merge_commit = pr_data.get("mergeCommit", {})
    commit_id = merge_commit.get("oid", "") if merge_commit else pr_data.get("headRefOid", "")
    file_contents: dict[str, str] = {}
    if commit_id:
        for file_path in extract_file_paths_from_patch(patch_test):
            try:
                file_contents[file_path] = gh_client.get_file_content(file_path, commit_id)
            except Exception:
                logger.debug("Could not fetch file content for %s", file_path)
    try:
        extract_tests_from_patch(patch_test, file_contents)
    except NoTestsExtractedError:
        return fail("No testable functions found in test patch")

    return ScreeningResult(pr_number=pr_number, repo=repo, passed=True)


def collect_gh_entry(
    pr_number: int,
    output: Path,
    environment_setup_version: str,
    repo: str = "microsoft/BCApps",
) -> None:
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
            environment_setup_version=environment_setup_version,
            test_patch=patch_test,
            fail_to_pass=fail_to_pass,
            project_paths=project_paths,
        )

    except Exception as exc:
        logger.exception("Failed to collect dataset entry")
        raise typer.Exit(code=1) from exc

    try:
        entry.save_to_file(output)
    except OSError as exc:
        logger.exception("Failed to write dataset entry")
        raise typer.Exit(code=1) from exc

    logger.info(f"Saved dataset entry {entry.instance_id} to {output}")
