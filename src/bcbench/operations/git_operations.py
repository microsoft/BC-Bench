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


def stage_and_get_diff(repo_path: Path, project_paths: list[str] | None = None) -> str:
    """Stage specified project changes and get the git diff.

    This function handles selective staging of changes and ensures only intended
    modifications are included in the diff. It can handle various scenarios including
    pre-staged files and unintended changes.

    Args:
        repo_path: Path to the git repository
        project_paths: Optional list of project paths to include in diff. If provided,
                      only changes in these paths will be staged and included in the diff.
                      Other paths will be cleaned to revert unintended changes.
                      If None, all *.al files will be staged.

    Returns:
        String containing the git diff patch

    Raises:
        EmptyDiffError: If the generated diff is empty (agent made no changes in specified paths)
        RuntimeError: If there are pre-staged changes that conflict with the operation
    """
    try:
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

        if project_paths:
            logger.info(f"Staging only changes in project paths: {project_paths}")
            # Stage only files in specified project paths (recursively)
            for project_path in project_paths:
                # Use -- to separate pathspec from options
                result = subprocess.run(
                    ["git", "add", "--", f"{project_path}"],
                    check=False,
                    cwd=repo_path,
                    capture_output=True,
                    encoding="utf-8",
                    text=True,
                )
                if result.returncode != 0:
                    logger.error(f"Failed to stage {project_path}: {result.stderr}")
                    raise RuntimeError(f"Failed to stage project path {project_path}: {result.stderr}")

            # Clean any unstaged changes (revert unintended changes to other projects)
            subprocess.run(["git", "checkout", "--", "."], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
            subprocess.run(["git", "clean", "-fd"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
            logger.info("Cleaned unstaged changes in other project paths")
        else:
            logger.info("Staging all *.al file changes")
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
            logger.error("Generated diff is empty - agent made no changes in specified paths")
            raise EmptyDiffError()

        return patch
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to stage and get git diff: {e.stderr}")
        raise
