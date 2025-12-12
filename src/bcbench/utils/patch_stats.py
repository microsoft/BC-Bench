"""Utilities for computing patch statistics."""

from unidiff import PatchSet

__all__ = ["count_files_in_patch", "count_lines_in_patch"]


def count_files_in_patch(patch: str) -> int:
    """Count the number of files modified in a patch.

    Args:
        patch: The diff/patch string to analyze

    Returns:
        Number of files in the patch
    """
    if not patch:
        return 0

    patch_set = PatchSet(patch)
    return len(patch_set)


def count_lines_in_patch(patch: str) -> int:
    """Count the total number of lines changed (added + removed) in a patch.

    Args:
        patch: The diff/patch string to analyze

    Returns:
        Total number of lines changed (added + removed)
    """
    if not patch:
        return 0

    patch_set = PatchSet(patch)
    return patch_set.added + patch_set.removed
