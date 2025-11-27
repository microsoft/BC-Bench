"""Collection module for gathering dataset entries from GitHub PRs."""

import re
from pathlib import Path
from typing import Any

import typer
from unidiff import PatchSet
from unidiff.errors import UnidiffParseError

from bcbench.collection.build_entry import save_problem_statement
from bcbench.collection.gh_client import GHClient
from bcbench.collection.patch_utils import separate_patches
from bcbench.config import get_config
from bcbench.dataset import DatasetEntry, TestEntry
from bcbench.exceptions import CollectionError, NoTestsExtractedError
from bcbench.logger import get_logger
from bcbench.operations.test_operations import extract_codeunit_id_from_content

logger = get_logger(__name__)
_config = get_config()

# Default BC environment setup version for GitHub-sourced entries
DEFAULT_ENVIRONMENT_VERSION = "26.0"


def _find_project_paths_from_diff(diff: str) -> list[str]:
    """Find project paths from a diff based on file path patterns.

    Since we don't have the repo locally, we infer project paths from the diff paths.
    BC projects typically have paths like:
    - App/Apps/W1/<ProjectName>/app/
    - App/Apps/W1/<ProjectName>/test/
    - App/Layers/W1/<ProjectName>/
    """
    if not diff or not str(diff).strip():
        raise CollectionError("Diff data is empty or None")

    try:
        patch_set = PatchSet(str(diff))
    except UnidiffParseError as e:
        raise CollectionError(f"Failed to parse diff data: {e}") from None

    project_paths: set[str] = set()

    for patched_file in patch_set:
        if not patched_file.path:
            continue

        # Extract the directory containing the file
        path_parts = patched_file.path.replace("\\", "/").split("/")

        # Look for 'app' or 'test' directory to find the project root
        # Skip the first component since paths often start with 'App' (capital A)
        for i in range(1, len(path_parts)):
            part = path_parts[i]
            if part.lower() in ("app", "test"):
                # Take path up to and including this directory
                project_path = "/".join(path_parts[: i + 1])
                if project_path:
                    project_paths.add(project_path)
                break

    return sorted(project_paths)


def _extract_tests_from_patch(generated_patch: str, gh_client: GHClient, ref: str) -> list[TestEntry]:
    """Extract test entries from an AL code patch using GitHub API to fetch file contents.

    Args:
        generated_patch: A git diff patch containing AL code with test procedures
        gh_client: GitHub client for fetching file contents
        ref: The git ref to fetch file contents from

    Returns:
        List of TestEntry with codeunitID and functionName

    Raises:
        NoTestsExtractedError: If no test entries are found in the patch
    """
    test_entries: list[TestEntry] = []
    current_codeunit_id: int | None = None

    # Pattern to match test procedure declarations that are ADDED (have + marker)
    procedure_pattern = r"^\+\s*procedure\s+(\w+)\s*\("

    # Pattern to match [Test] attribute that is ADDED (have + marker)
    test_attribute_pattern = r"^\+\s*\[Test\]"

    # Pattern to match diff file headers: diff --git a/<path> b/<path>
    file_header_pattern = r"^diff --git a/(.+) b/(.+)$"

    lines = generated_patch.split("\n")
    found_test_attribute = False

    for line in lines:
        file_header_match = re.match(file_header_pattern, line)
        if file_header_match:
            current_file_path = file_header_match.group(2)
            if current_file_path:
                try:
                    content = gh_client.get_file_content(current_file_path, ref)
                    current_codeunit_id = extract_codeunit_id_from_content(content, current_file_path)
                except Exception as e:
                    logger.warning("Failed to get codeunit ID for %s: %s", current_file_path, e)
                    current_codeunit_id = None
            continue

        if re.match(test_attribute_pattern, line):
            found_test_attribute = True
            continue

        if found_test_attribute and current_codeunit_id is not None:
            procedure_match = re.match(procedure_pattern, line)
            if procedure_match:
                function_name = procedure_match.group(1)

                existing_entry = None
                for entry in test_entries:
                    if entry.codeunitID == current_codeunit_id:
                        existing_entry = entry
                        break

                if existing_entry:
                    if function_name not in existing_entry.functionName:
                        existing_entry.functionName.add(function_name)
                else:
                    test_entries.append(TestEntry(codeunitID=current_codeunit_id, functionName={function_name}))

                found_test_attribute = False
            elif not line.startswith("+"):
                found_test_attribute = False

    if not test_entries:
        raise NoTestsExtractedError()

    return test_entries


def collect_gh_entry(pr_number: int, output: Path, repo: str = "microsoft/bcapps") -> None:
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

        project_paths = _find_project_paths_from_diff(patch)

        fail_to_pass = _extract_tests_from_patch(patch_test, gh_client, commit_id)

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
