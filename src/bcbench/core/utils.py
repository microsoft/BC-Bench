"""Shared utilities for BC Bench Python scripts."""

from __future__ import annotations

import re
import subprocess
from html import unescape
from typing import List, Set, Tuple
from unidiff import PatchSet
from pathlib import Path


def _get_git_root() -> Path:
    """Get the git root directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).parent,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        # Fallback to file-based resolution if not in a git repo
        return Path(__file__).parent.parent.parent.parent


def _get_schema_path() -> Path:
    """Get the schema file path from the dataset directory."""
    git_root = _get_git_root()
    return git_root / "dataset" / "schema.json"


# Constants - dynamically resolve BC-Bench root from git root
BC_BENCH_ROOT = _get_git_root()
DATASET_PATH = BC_BENCH_ROOT / "dataset" / "bcbench_nav.jsonl"
DATASET_SCHEMA_PATH = _get_schema_path()
NAV_REPO_PATH = BC_BENCH_ROOT.parent / "NAV"

# ANSI color codes
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
RED = "\033[31m"
GREY = "\033[90m"
RESET = "\033[0m"

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


def colored(text: str, color: str) -> str:
    allowed_colors = {CYAN, GREEN, YELLOW, BLUE, MAGENTA, RED, GREY}
    if color not in allowed_colors:
        raise ValueError(
            "Invalid color. Must be one of: CYAN, GREEN, YELLOW, BLUE, MAGENTA, RED, GREY"
        )
    return f"{color}{text}{RESET}"


def extract_patches(base_commit_id: str, commit_id: str) -> Tuple[str, str, str]:
    """Return the gold and fix patch between two commits in the NAV repository."""
    repo_path = NAV_REPO_PATH
    if not repo_path.exists():
        raise FileNotFoundError(
            f"NAV repository not found at {repo_path}. Adjust NAV_REPO_PATH in constants.py."
        )

    result = subprocess.run(
        ["git", "diff", base_commit_id, commit_id],
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


def strip_html(html_text: str) -> str:
    """Strip HTML tags and unescape HTML entities from text."""
    if not html_text:
        return ""
    clean = re.sub(r"<.*?>", "", html_text)
    clean = unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def normalize_repo_subpath(value: str) -> str:
    """Normalize a repository-relative path stored in the dataset."""
    return value.strip().lstrip("/\\")


def find_project_paths_from_patch(patch: str) -> List[str]:
    """Derive unique project paths (directories containing app.json) from a unified diff."""

    if not patch or not str(patch).strip():
        raise ValueError("Patch data is empty or None.")

    try:
        patch_set = PatchSet(str(patch))
    except Exception:
        raise ValueError("Failed to parse patch data.")

    project_paths: Set[str] = set()

    for patched_file in patch_set:
        if not patched_file.path:
            continue

        current_dir = (NAV_REPO_PATH / patched_file.path).parent

        while True:
            try:
                relative_dir = current_dir.relative_to(NAV_REPO_PATH)
            except ValueError:
                break

            app_json_path = current_dir / "app.json"
            if app_json_path.is_file():
                normalized = normalize_repo_subpath(str(relative_dir))
                if normalized:
                    project_paths.add(normalized)
                break

            if current_dir == NAV_REPO_PATH:
                break

            current_dir = current_dir.parent

    return sorted(project_paths)
