"""Setup operations for repository preparation."""

from pathlib import Path

import yaml

from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.logger import get_logger
from bcbench.operations.git_operations import apply_patch, checkout_commit, clean_repo, commit_changes
from bcbench.operations.instruction_operations import copy_problem_statement_folder
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)
_config = get_config()

__all__ = ["_get_test_generation_input_mode", "setup_repo_postbuild", "setup_repo_prebuild"]


def _get_test_generation_input_mode() -> str:
    """Read test-generation input mode from shared agent config.

    Returns:
        str: The validated input mode: "gold-patch", "problem-statement", or "both"

    Raises:
        ValueError: If the input mode is not one of the valid values
    """
    config_file: Path = _config.paths.agent_share_dir / "config.yaml"
    shared_config = yaml.safe_load(config_file.read_text())
    input_mode: str = shared_config.get("prompt", {}).get("test-generation-input", "problem-statement")

    valid_modes: set[str] = {"gold-patch", "problem-statement", "both"}
    if input_mode not in valid_modes:
        raise ValueError(f"Invalid test-generation-input mode: '{input_mode}'. Must be one of {valid_modes}. Note: Use hyphens, not underscores (e.g., 'gold-patch' not 'gold_patch')")

    return input_mode


def _is_under_symlink(path: Path, root: Path) -> bool:
    current = path
    while current != root and current != current.parent:
        if current.is_symlink():
            return True
        current = current.parent
    return False


def _remove_table_scope_onprem(repo_path: Path) -> None:
    """Remove 'Scope = OnPrem;' from the top 50 lines of all *.Table.al files under the repo."""
    table_files = [f for f in repo_path.rglob("*.Table.al") if not _is_under_symlink(f, repo_path)]
    if not table_files:
        return

    logger.info(f"Removing 'Scope = OnPrem;' from {len(table_files)} Table.al files")
    modified_count = 0
    for table_file in table_files:
        try:
            lines = table_file.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        except (UnicodeDecodeError, OSError):
            continue
        head = lines[:50]
        target_index = next((i for i, line in enumerate(head) if line.strip() == "Scope = OnPrem;"), None)
        if target_index is not None:
            del lines[target_index]
            table_file.write_text("".join(lines), encoding="utf-8")
            modified_count += 1

    if modified_count:
        logger.info(f"Removed 'Scope = OnPrem;' from {modified_count} Table.al files")


def setup_repo_prebuild(entry: DatasetEntry, repo_path: Path) -> None:
    """Setup repository before building - clean and checkout base commit.

    This is the first phase of repo setup that should be called BEFORE build_and_publish_projects.
    It prepares a clean slate at the base commit without any patches or problem statements.

    Args:
        entry: Dataset entry with instance metadata
        repo_path: Path to the repository
    """
    clean_repo(repo_path)
    checkout_commit(repo_path, entry.base_commit)
    _remove_table_scope_onprem(repo_path)
    commit_changes(repo_path, "Remove Scope = OnPrem from Table.al files")


def setup_repo_postbuild(entry: DatasetEntry, repo_path: Path, category: EvaluationCategory) -> None:
    """Setup repository after building - apply patches and copy problem statements.

    This is the second phase of repo setup that should be called AFTER build_and_publish_projects.
    For test-generation, this ensures the gold patch is applied only after the base code is built,
    so the agent sees the fixed code but tests run against the unfixed published app.

    Args:
        entry: Dataset entry with instance metadata
        repo_path: Path to the repository
        category: Evaluation category (bug-fix or test-generation)
    """
    if category == EvaluationCategory.TEST_GENERATION:
        input_mode: str = _get_test_generation_input_mode()
        logger.info(f"Test generation input mode: {input_mode}")
        match input_mode:
            case "gold-patch":
                apply_patch(repo_path, entry.patch, f"{entry.instance_id} gold patch")
            case "both":
                apply_patch(repo_path, entry.patch, f"{entry.instance_id} gold patch")
                copy_problem_statement_folder(entry, repo_path)
            case "problem-statement":
                copy_problem_statement_folder(entry, repo_path)
            case _:
                raise ValueError(f"Unhandled test generation input mode: {input_mode}")
    else:
        copy_problem_statement_folder(entry, repo_path)
