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


def clean_project_paths(repo_path: Path, project_paths: list[str]) -> None:
    """Clean specific project paths by discarding all changes in those directories.

    This is useful when agents make unintended changes to specific projects
    that should be reverted before applying patches.

    Args:
        repo_path: Path to the git repository
        project_paths: List of relative project paths to clean
    """
    if not project_paths:
        logger.debug("No project paths provided to clean")
        return

    logger.info(f"Cleaning project paths: {project_paths}")

    try:
        # Reset changes in all specified paths with a single git command
        subprocess.run(["git", "checkout", "HEAD", "--", *project_paths], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

        # Clean untracked files in all specified paths
        # Note: git clean doesn't support multiple paths in a single command efficiently,
        # so we need to call it for each path
        for project_path in project_paths:
            subprocess.run(["git", "clean", "-fd", project_path], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

        logger.info(f"Project paths cleaned successfully: {project_paths}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to clean project paths: {e.stderr}")
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


def get_generated_diff(repo_path: Path, project_paths: list[str] | None = None) -> str:
    """Get agent generated git diff as a string.

    Args:
        repo_path: Path to the git repository
        project_paths: Optional list of project paths to include in diff. If provided,
                      only changes in these paths will be staged and included in the diff.
                      Other paths will be cleaned to revert unintended changes.

    Raises:
        EmptyDiffError: If the generated diff is empty (agent made no changes)
    """
    try:
        logger.info("Getting git diff")

        if project_paths:
            # Stage only *.al files in specified project paths
            for project_path in project_paths:
                subprocess.run(["git", "add", f"{project_path}/*.al"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

            # Clean any unstaged changes (revert unintended changes to other projects)
            subprocess.run(["git", "checkout", "--", "."], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
            subprocess.run(["git", "clean", "-fd"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        else:
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
