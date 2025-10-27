"""Shared utilities for BC Bench Python scripts."""

from __future__ import annotations

import os
import re
import subprocess
from html import unescape
from pathlib import Path

from unidiff import PatchSet


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


# Constants - dynamically resolve BC-Bench root from git root
_BC_BENCH_ROOT = _get_git_root()
DATASET_PATH = _BC_BENCH_ROOT / "dataset" / "bcbench_nav.jsonl"
DATASET_SCHEMA_PATH = _BC_BENCH_ROOT / "dataset" / "schema.json"
NAV_REPO_PATH = _BC_BENCH_ROOT.parent / "NAV"
PS_SCRIPT_PATH = _BC_BENCH_ROOT / "scripts"

__all__ = [
    "DATASET_PATH",
    "DATASET_SCHEMA_PATH",
    "NAV_REPO_PATH",
    "PS_SCRIPT_PATH",
    "find_project_paths_from_patch",
    "normalize_repo_subpath",
    "strip_html",
    "write_github_output",
]


def strip_html(html_text: str) -> str:
    """Strip HTML tags and unescape HTML entities from text."""
    if not html_text:
        return ""
    clean = re.sub(r"<.*?>", "", html_text)
    clean = unescape(clean)
    return re.sub(r"\s+", " ", clean).strip()


def normalize_repo_subpath(value: str) -> str:
    """Normalize a repository-relative path stored in the dataset."""
    return value.strip().lstrip("/\\")


def find_project_paths_from_patch(repo_path: Path, patch: str) -> list[str]:
    """Derive unique project paths (directories containing app.json) from a unified diff."""

    if not patch or not str(patch).strip():
        raise ValueError("Patch data is empty or None.")

    try:
        patch_set = PatchSet(str(patch))
    except Exception:
        raise ValueError("Failed to parse patch data.") from None

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
                normalized = normalize_repo_subpath(str(relative_dir))
                if normalized:
                    project_paths.add(normalized)
                break

            if current_dir == repo_path:
                break

            current_dir = current_dir.parent

    return sorted(project_paths)


def write_github_output(key: str, value: str) -> None:
    """Write a value to GitHub Actions output."""
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")
