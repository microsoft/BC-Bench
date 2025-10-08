"""Core utilities and shared components for bcbench."""

from bcbench.core.utils import (
    extract_patches,
    strip_html,
    normalize_repo_subpath,
    find_project_paths_from_patch,
    colored,
    CYAN,
    GREEN,
    YELLOW,
    BLUE,
    MAGENTA,
    RED,
    GREY,
    BC_BENCH_ROOT,
    DATASET_PATH,
    DATASET_SCHEMA_PATH,
    NAV_REPO_PATH,
)


__all__ = [
    "extract_patches",
    "strip_html",
    "normalize_repo_subpath",
    "find_project_paths_from_patch",
    "colored",
    "CYAN",
    "GREEN",
    "YELLOW",
    "BLUE",
    "MAGENTA",
    "RED",
    "GREY",
    "BC_BENCH_ROOT",
    "DATASET_PATH",
    "DATASET_SCHEMA_PATH",
    "NAV_REPO_PATH",
]
