"""Builder functions for creating DatasetEntry from ADO sources."""

from pathlib import Path
from typing import Any

from bcbench.collection.ado_utils import extract_creation_date, extract_problem_statement
from bcbench.collection.patch_utils import extract_patches, find_project_paths_from_patch
from bcbench.collection.version_resolver import determine_environment_setup_version
from bcbench.dataset import DatasetEntry


def build_dataset_entry_from_ado(
    *,
    pr_number: int,
    repo_path: Path,
    pr_data: dict[str, Any],
    work_item_data: dict[str, Any],
    base_commit: str,
    commit: str,
    diff_path: str = "",
) -> DatasetEntry:
    """Build a DatasetEntry from Azure DevOps PR and work item data."""
    created_at = extract_creation_date(pr_data)
    patch, patch_fix, patch_test = extract_patches(repo_path, base_commit, commit, diff_path=diff_path)
    problem_statement = extract_problem_statement(work_item_data)
    hints = ""
    version = determine_environment_setup_version(commit)

    return DatasetEntry(
        instance_id=f"microsoftInternal__NAV-{pr_number}",
        base_commit=base_commit,
        commit=commit,
        pr_number=pr_number,
        created_at=created_at,
        patch=patch_fix,
        environment_setup_version=version,
        test_patch=patch_test,
        problem_statement=problem_statement,
        hints_text=hints,
        project_paths=find_project_paths_from_patch(repo_path, patch),
        _raw_pr_data=pr_data,
        _raw_work_item_data=work_item_data,
    )
