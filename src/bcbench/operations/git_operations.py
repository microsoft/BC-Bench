"""Git repository operations."""

import subprocess
import tempfile
from pathlib import Path

from unidiff import PatchSet

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
    subprocess.run(
        ["git", "checkout", commit],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    logger.info(f"Commit {commit} checked out")


def apply_patch(repo_path: Path, patch_content: str, patch_name: str = "patch") -> None:
    logger.info(f"Applying {patch_name}")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".patch", delete=False, encoding="utf-8"
    ) as f:
        f.write(patch_content)
        patch_file = f.name

    try:
        result = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", patch_file],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error(
                f"{patch_name.capitalize()} application failed: {result.stderr}"
            )
            raise ValueError(f"Failed to apply {patch_name}")
        logger.info(f"{patch_name.capitalize()} applied successfully")
    finally:
        Path(patch_file).unlink(missing_ok=True)


def extract_patches(
    repo_path: Path, base_commit_id: str, commit_id: str, diff_path: str = ""
) -> tuple[str, str, str]:
    """Return the gold and fix patch between two commits in the given repository."""
    if not repo_path.exists():
        raise FileNotFoundError(f"Repository not found at {repo_path}.")

    git_cmd = ["git", "diff", base_commit_id, commit_id]
    if diff_path:
        git_cmd.append("--")
        git_cmd.append(diff_path)

    result = subprocess.run(
        git_cmd,
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    patch = result.stdout

    if not patch:
        raise ValueError("No patch data found between the specified commits.")

    patch_test: str = ""
    patch_fix: str = ""
    for hunk in PatchSet(patch):
        if any(word in hunk.path.lower() for word in ("test", "tests")):
            patch_test += str(hunk)
        else:
            patch_fix += str(hunk)
    return patch, patch_fix, patch_test
