"""Git repository operations."""

import subprocess
import tempfile
from pathlib import Path

from bcbench.exceptions import PatchApplicationError
from bcbench.logger import get_logger

logger = get_logger(__name__)


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

    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False, encoding="utf-8") as f:
        f.write(patch_content)
        patch_file = f.name

    try:
        subprocess.run(
            ["git", "apply", "--whitespace=nowarn", patch_file],
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
