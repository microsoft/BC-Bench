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
    subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    subprocess.run(["git", "clean", "-fd"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    logger.info("Repository cleaned successfully")


def clean_project_paths(repo_path: Path, project_paths: list[str]) -> None:
    """Clean specific project paths by unstaging and discarding all changes in those directories.

    This function first unstages any staged changes in the specified paths, then reverts
    modified files and removes untracked files. This is useful when agents make unintended
    changes to projects they shouldn't touch (e.g., test files in bugfix, app files in testgen).

    Args:
        repo_path: Path to the git repository
        project_paths: List of relative project paths to clean

    Raises:
        subprocess.CalledProcessError: If git operations fail
    """
    if not project_paths:
        logger.error("No project paths provided to clean")
        raise ValueError("No project paths provided to clean")

    logger.info(f"Cleaning project paths: {project_paths}")

    # First, unstage any staged changes in these paths
    for project_path in project_paths:
        subprocess.run(["git", "reset", "HEAD", "--", project_path], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    # Then revert modified files in these paths
    subprocess.run(["git", "checkout", "HEAD", "--", *project_paths], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    # Finally, remove untracked files in these paths
    for project_path in project_paths:
        subprocess.run(["git", "clean", "-fd", project_path], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    logger.info(f"Project paths cleaned successfully: {project_paths}")


def checkout_commit(repo_path: Path, commit: str) -> None:
    logger.info(f"Checking out commit: {commit}")
    subprocess.run(["git", "checkout", commit], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    logger.info(f"Commit {commit} checked out")


def commit_changes(repo_path: Path, message: str) -> None:
    logger.info(f"Committing changes: {message}")
    subprocess.run(["git", "add", "-A"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    subprocess.run(
        ["git", "-c", "user.name=bcbench", "-c", "user.email=bcbench@noreply", "commit", "--allow-empty", "-m", message],
        cwd=repo_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=True,
    )
    logger.info("Changes committed")


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


def stage_and_get_diff(repo_path: Path) -> str:
    """Stage all *.al file changes and get the git diff.

    This function stages all *.al files in the repository and returns the diff.
    It does NOT stage app.json files as dataset doesn't include app.json changes yet.

    Args:
        repo_path: Path to the git repository

    Returns:
        String containing the git diff patch

    Raises:
        EmptyDiffError: If the generated diff is empty (agent made no changes)
    """
    logger.info("Staging *.al file changes and getting git diff")

    # Stage all changes, so new files can be captured in the diff
    # only focus on *.al files for now
    subprocess.run(["git", "add", "*.al"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    # Get diff of staged changes against HEAD
    result = subprocess.run(
        ["git", "diff", "--cached", "--", ".", ":!*.docx", ":!**/app.json", ":!*.md"],
        cwd=repo_path,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    )
    patch: str = result.stdout
    logger.info("Git diff retrieved successfully")
    logger.debug(f"Generated diff:\n{patch}")

    if not patch:
        logger.error("Generated diff is empty - agent made no changes")
        raise EmptyDiffError()

    return patch
