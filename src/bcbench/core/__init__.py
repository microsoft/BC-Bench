"""Core utilities and shared components for bcbench."""

from bcbench.core.utils import extract_patches, strip_html, normalize_repo_subpath, find_project_paths_from_patch, BC_BENCH_ROOT, DATASET_PATH, DATASET_SCHEMA_PATH, NAV_REPO_PATH, PS_SCRIPT_PATH
from bcbench.core.git_operations import (
    clean_repo,
    checkout_commit,
    apply_patch,
)
from bcbench.core.bc_operations import (
    build_and_publish_projects,
    run_tests,
)


__all__ = [
    "extract_patches",
    "strip_html",
    "normalize_repo_subpath",
    "find_project_paths_from_patch",
    "BC_BENCH_ROOT",
    "DATASET_PATH",
    "DATASET_SCHEMA_PATH",
    "NAV_REPO_PATH",
    "PS_SCRIPT_PATH",
    "clean_repo",
    "checkout_commit",
    "apply_patch",
    "build_and_publish_projects",
    "run_tests",
]
