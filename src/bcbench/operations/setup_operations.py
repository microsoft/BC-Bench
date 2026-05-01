"""Setup operations for repository preparation."""

from pathlib import Path

from bcbench.dataset.dataset_entry import BaseDatasetEntry
from bcbench.logger import get_logger
from bcbench.operations.git_operations import checkout_commit, clean_repo

logger = get_logger(__name__)

__all__ = ["setup_repo_prebuild"]


def setup_repo_prebuild(entry: BaseDatasetEntry, repo_path: Path) -> None:
    """Setup repository before building - clean and checkout base commit.

    This is the first phase of repo setup that should be called BEFORE build_and_publish_projects.
    It prepares a clean slate at the base commit without any patches or problem statements.
    Skips for entries without a base_commit (e.g. categories that start from a blank project).

    Args:
        entry: Dataset entry with instance metadata
        repo_path: Path to the repository
    """
    if not entry.base_commit:
        logger.info(f"Skipping prebuild setup for {entry.instance_id} (no base_commit)")
        return

    clean_repo(repo_path)
    checkout_commit(repo_path, entry.base_commit)
