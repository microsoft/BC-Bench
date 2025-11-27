"""Builder functions for creating DatasetEntry from ADO sources."""

from pathlib import Path
from typing import Any

from bcbench.collection.ado_utils import extract_creation_date, extract_problem_statement
from bcbench.collection.patch_utils import extract_file_paths_from_patch, extract_patches, find_project_paths_from_diff
from bcbench.collection.version_resolver import determine_environment_setup_version
from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.operations.git_operations import checkout_commit
from bcbench.operations.test_operations import extract_tests_from_patch

_config = get_config()


def save_problem_statement(
    *,
    instance_id: str,
    problem_statement: str,
    hints: str = "",
    problem_statement_dir: Path = _config.paths.problem_statement_dir,
    filename: str = _config.file_patterns.problem_statement_readme,
) -> None:
    """Save the problem statement to a file.

    Args:
        instance_id: Unique identifier for the dataset entry
        problem_statement: The main problem statement content
        hints: Optional hints to append to the problem statement
        problem_statement_dir: Directory to save problem statements (defaults to config)
        filename: Name of the problem statement file (defaults to config)
    """
    output_dir = problem_statement_dir / instance_id
    output_dir.mkdir(parents=True, exist_ok=True)

    content = problem_statement
    if hints:
        content += f"\n\n## Hints\n\n{hints}"

    readme_path = output_dir / filename
    readme_path.write_text(content, encoding="utf-8")


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
    created_at = extract_creation_date(pr_data)
    patch, patch_fix, patch_test = extract_patches(repo_path, base_commit, commit, diff_path=diff_path)
    problem_statement, hints = extract_problem_statement(work_item_data)
    version = determine_environment_setup_version(commit)
    checkout_commit(repo_path, commit)

    file_contents: dict[str, str] = {}
    for file_path in extract_file_paths_from_patch(patch_test):
        full_path = repo_path / file_path
        file_contents[file_path] = full_path.read_text(encoding="utf-8")

    fail_to_pass = extract_tests_from_patch(patch_test, file_contents)

    instance_id: str = f"microsoftInternal__NAV-{pr_number}"

    save_problem_statement(
        instance_id=instance_id,
        problem_statement=problem_statement,
        hints=hints,
    )

    return DatasetEntry(
        instance_id=instance_id,
        base_commit=base_commit,
        created_at=created_at,
        patch=patch_fix,
        environment_setup_version=version,
        test_patch=patch_test,
        fail_to_pass=fail_to_pass,
        project_paths=find_project_paths_from_diff(patch),
    )
