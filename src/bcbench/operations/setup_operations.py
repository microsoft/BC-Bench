"""Setup operations for repository preparation."""

from pathlib import Path

import yaml

from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.logger import get_logger
from bcbench.operations.git_operations import apply_patch, checkout_commit, clean_repo
from bcbench.operations.instruction_operations import copy_problem_statement_folder
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)
_config = get_config()

__all__ = ["setup_repo"]


def _get_test_generation_input_mode() -> str:
    """Read test-generation input mode from copilot config.

    Returns:
        str: The validated input mode, either "gold-patch" or "problem-statement"

    Raises:
        ValueError: If the input mode is not one of the valid values
    """
    config_file: Path = _config.paths.agent_dir / "config.yaml"
    copilot_config = yaml.safe_load(config_file.read_text())
    input_mode: str = copilot_config.get("prompt", {}).get("test-generation-input", "problem-statement")

    valid_modes: set[str] = {"gold-patch", "problem-statement"}
    if input_mode not in valid_modes:
        raise ValueError(f"Invalid test-generation-input mode: '{input_mode}'. Must be one of {valid_modes}. Note: Use hyphens, not underscores (e.g., 'gold-patch' not 'gold_patch')")

    return input_mode


def setup_repo(entry: DatasetEntry, repo_path: Path, category: EvaluationCategory) -> None:
    """Setup repository for evaluation without building.

    This function prepares the repository for agent execution by:
    1. Cleaning the repo to remove any uncommitted changes
    2. Checking out the base commit
    3. For test-generation with gold-patch mode: applying the gold patch
    4. For all other cases: copying the problem statement folder

    This is shared between the run command (no BC container) and evaluate command.
    The evaluate pipeline additionally calls build_and_publish_projects after this.

    Args:
        entry: Dataset entry with instance metadata
        repo_path: Path to the repository
        category: Evaluation category (bug-fix or test-generation)
    """
    clean_repo(repo_path)
    checkout_commit(repo_path, entry.base_commit)

    if category == EvaluationCategory.TEST_GENERATION:
        input_mode: str = _get_test_generation_input_mode()
        logger.info(f"Test generation input mode: {input_mode}")
        if input_mode == "gold-patch":
            apply_patch(repo_path, entry.patch, f"{entry.instance_id} gold patch")
        else:
            copy_problem_statement_folder(entry, repo_path)
    else:
        copy_problem_statement_folder(entry, repo_path)
