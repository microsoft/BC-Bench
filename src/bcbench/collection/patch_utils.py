"""Utilities for working with git patches and project paths."""

import subprocess
from pathlib import Path

from unidiff import PatchSet

from bcbench.config import get_config
from bcbench.exceptions import CollectionError
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()


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

    patch_test: str = ""
    patch_fix: str = ""
    test_identifiers = _config.file_patterns.test_project_identifiers
    for hunk in PatchSet(patch):
        if any(identifier in hunk.path.lower() for identifier in test_identifiers):
            patch_test += str(hunk)
        else:
            patch_fix += str(hunk)

    return patch, patch_fix, patch_test


def find_project_paths_from_patch(repo_path: Path, patch: str) -> list[str]:
    """Find project paths (directories containing app.json) from a patch."""
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

        current_dir = (repo_path / patched_file.path).parent

        while True:
            try:
                relative_dir = current_dir.relative_to(repo_path)
            except ValueError:
                break

            app_json_path = current_dir / "app.json"
            if app_json_path.is_file():
                normalized = str(relative_dir).strip().lstrip("/\\")
                if normalized:
                    project_paths.add(normalized)
                break

            if current_dir == repo_path:
                break

            current_dir = current_dir.parent

    return sorted(project_paths)
