"""Git repository operations."""

import subprocess
import tempfile
from pathlib import Path

from bcbench.config import get_config
from bcbench.exceptions import EmptyDiffError, PatchApplicationError
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()


def clean_repo(repo_path: Path) -> None:
    """Clean the repository by discarding all changes, including staged files and untracked files."""
    logger.info(f"Cleaning repository: {repo_path}")

    try:
        subprocess.run(
            ["git", "reset", "--hard", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )

        subprocess.run(
            ["git", "clean", "-fd"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )

        logger.info("Repository cleaned successfully")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to clean repository: {e.stderr}")
        raise


def checkout_commit(repo_path: Path, commit: str) -> None:
    logger.info(f"Checking out commit: {commit}")
    try:
        subprocess.run(
            ["git", "checkout", commit],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to checkout commit {commit}: {e.stderr}")
        raise
    logger.info(f"Commit {commit} checked out")


def apply_patch(repo_path: Path, patch_content: str, patch_name: str = "patch") -> None:
    logger.info(f"Applying {patch_name}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=_config.file_patterns.patch_pattern, delete=False, encoding="utf-8") as f:
        f.write(patch_content)
        patch_file = f.name

    try:
        subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "--ignore-whitespace", patch_file],
            cwd=repo_path,
            capture_output=True,
            check=True,
            text=True,
        )

        logger.info(f"{patch_name.capitalize()} applied successfully")
    except subprocess.CalledProcessError as e:
        logger.error(f"{patch_name.capitalize()} application failed: {e.stderr}")
        raise PatchApplicationError(patch_name, e.stderr) from e
    finally:
        Path(patch_file).unlink(missing_ok=True)


def get_gernerated_diff(repo_path: Path) -> str:
    """Get agent generated git diff as a string.

    Args:
        result_dir: Path to the result directory
        repo_path: Path to the git repository

    Raises:
        EmptyDiffError: If the generated diff is empty (agent made no changes)
    """
    try:
        logger.info("Getting git diff")

        # Stage all changes, so new files can be captured in the diff
        subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_path,
            check=True,
        )

        # Get diff of staged changes against HEAD
        result = subprocess.run(
            ["git", "diff", "--cached", "--", ".", ":!*.docx", ":!**/app.json"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        patch: str = result.stdout.strip()
        logger.info("Git diff retrieved successfully")
        logger.debug(f"Generated diff:\n{patch}")
        if not patch:
            logger.error("Generated diff is empty")
            raise EmptyDiffError()
        return patch
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get git diff: {e.stderr}")
        raise
