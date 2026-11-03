import logging
from pathlib import Path
from shutil import copytree, rmtree

from bcbench.dataset.dataset_entry import WORKSPACE_PROBLEM_DIR, RepoGroundedEntry
from bcbench.paths import AGENT_SHARE_DIR

logger = logging.getLogger(__name__)


def instructions_profile_dir(profile: str) -> Path:
    """Shipped instructions, skills and custom agents for a customization profile, shared by Copilot and Claude."""
    return AGENT_SHARE_DIR / "instructions" / profile


def copy_problem_statement_folder(entry: RepoGroundedEntry, repo_path: Path) -> None:
    """
    Copy problem statement folder to the testbed repository root.

    This makes the problem statement (including any screenshots) accessible to Copilot during evaluation.

    Args:
        entry: Dataset entry containing problem_statement path
        repo_path: Path to testbed repository where folder will be copied
    """
    source_dir: Path = entry.problem_statement_dir
    dest_dir: Path = repo_path / WORKSPACE_PROBLEM_DIR

    if dest_dir.exists():
        rmtree(dest_dir)

    copytree(source_dir, dest_dir)
    logger.info(f"Copied problem statement folder from {source_dir} to {dest_dir}")
