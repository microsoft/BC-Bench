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
        subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

        subprocess.run(["git", "clean", "-fd"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

        logger.info("Repository cleaned successfully")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to clean repository: {e.stderr}")
        raise


def checkout_commit(repo_path: Path, commit: str) -> None:
    logger.info(f"Checking out commit: {commit}")
    try:
        subprocess.run(["git", "checkout", commit], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
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
        subprocess.run(["git", "apply", "--whitespace=nowarn", "--ignore-whitespace", patch_file], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

        logger.info(f"{patch_name.capitalize()} applied successfully")
    except subprocess.CalledProcessError as e:
        logger.error(f"{patch_name.capitalize()} application failed: {e.stderr}")
        raise PatchApplicationError(patch_name, e.stderr) from e
    finally:
        Path(patch_file).unlink(missing_ok=True)


def stage_and_get_diff(repo_path: Path, project_paths: list[str]) -> str:
    """Stage changes (*.al only) under specified projects and get git diff, changes outside these projects are reverted to avoid conflicts when applying patches.

    Note:
        This function do NOT stage changes for app.json, as we do not have dataset including app.json changes yet.
        app.json will be changed when we build and publish the projects, probably need special handling in future (e.g. commit).

    Returns:
        String containing the git diff patch

    Raises:
        EmptyDiffError: If the generated diff is empty (agent made no changes in specified paths)
        RuntimeError: If there are pre-staged changes that conflict with the operation
    """
    logger.info("Staging changes and getting git diff")

    # Check for pre-staged changes that might conflict with our operation
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo_path,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    )
    pre_staged_files = result.stdout.strip()
    if pre_staged_files:
        logger.warning(f"Found pre-staged files: {pre_staged_files}")
        # Unstage all pre-staged files to avoid conflicts
        subprocess.run(["git", "reset", "HEAD"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        logger.info("Unstaged pre-staged files")

    logger.info(f"Staging only *.al file changes in project paths: {project_paths}")
    for project_path in project_paths:
        subprocess.run(["git", "add", "--", f"{project_path}", "*.al"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    subprocess.run(["git", "checkout", "--", "."], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    subprocess.run(["git", "clean", "-fd"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    logger.info("Cleaned unstaged changes in other project paths")

    result = subprocess.run(
        ["git", "diff", "--cached", "--", ".", ":!*.docx", ":!**/app.json", ":!*.md"],
        cwd=repo_path,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    )
    patch: str = result.stdout.strip()
    logger.info("Git diff retrieved successfully")
    logger.debug(f"Generated diff:\n{patch}")

    if not patch:
        logger.error("Generated diff is empty - agent made no changes in specified paths")
        raise EmptyDiffError()

    return patch
