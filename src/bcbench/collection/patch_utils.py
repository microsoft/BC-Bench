"""Utilities for working with git patches and project paths."""

import subprocess
from pathlib import Path

from unidiff import PatchSet

from bcbench.config import get_config
from bcbench.exceptions import CollectionError
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()


def separate_patches(diff: str, test_identifiers: tuple[str, ...]) -> tuple[str, str, str]:
    """Separate a diff into full, fix, and test patches.

    Args:
        diff: The full diff string
        test_identifiers: Tuple of identifiers to detect test files (e.g., "test", "tests")

    Returns:
        tuple: (full_patch, fix_patch, test_patch)

    Raises:
        CollectionError: If the diff is empty
    """
    if not diff:
        raise CollectionError("No diff data found")

    patch_test: str = ""
    patch_fix: str = ""
    for hunk in PatchSet(diff):
        if any(identifier in hunk.path.lower() for identifier in test_identifiers):
            patch_test += str(hunk)
        else:
            patch_fix += str(hunk)

    return diff, patch_fix, patch_test


def extract_patches(repo_path: Path, base_commit_id: str, commit_id: str, diff_path: str = "") -> tuple[str, str, str]:
    """Extract patches between two commits, separating test and fix patches.

    Returns:
        tuple: (full_patch, fix_patch, test_patch)
    """
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
        raise CollectionError("No patch data found between the specified commits")

    return separate_patches(patch, _config.file_patterns.test_project_identifiers)


def find_project_paths_from_diff(patch: str) -> list[str]:
    """Find project paths from a diff based on file path patterns.

    Infers project paths from the diff paths without needing local filesystem access.
    BC projects typically have paths like:
    - App/Apps/W1/<ProjectName>/app/
    - App/Apps/W1/<ProjectName>/test/
    - App/Layers/W1/<ProjectName>/

    Args:
        patch: The diff/patch string to analyze

    Returns:
        Sorted list of project paths

    Raises:
        CollectionError: If the patch is empty or cannot be parsed
    """
    if not patch or not str(patch).strip():
        raise CollectionError("Patch data is empty or None")

    try:
        patch_set = PatchSet(str(patch))
    except Exception:
        raise CollectionError("Failed to parse patch data") from None

    project_paths: set[str] = set()

    for patched_file in patch_set:
        if not patched_file.path:
            continue

        # Extract the directory containing the file
        path_parts = patched_file.path.replace("\\", "/").split("/")

        # Look for 'app' or 'test' directory to find the project root
        # Skip the first component since paths often start with 'App' (capital A)
        for i in range(1, len(path_parts)):
            part = path_parts[i]
            if part.lower() in ("app", "test"):
                # Take path up to and including this directory
                project_path = "/".join(path_parts[: i + 1])
                if project_path:
                    project_paths.add(project_path)
                break

    return sorted(project_paths)


def extract_file_paths_from_patch(patch: str) -> list[str]:
    """Extract file paths from a patch.

    Args:
        patch: The diff/patch string to analyze

    Returns:
        List of file paths referenced in the patch
    """
    if not patch:
        return []

    try:
        patch_set = PatchSet(str(patch))
    except Exception:
        return []

    return [patched_file.path for patched_file in patch_set if patched_file.path]
