"""Setup operations for repository preparation."""

import json
from pathlib import Path

from bcbench.dataset.dataset_entry import BaseDatasetEntry
from bcbench.logger import get_logger
from bcbench.operations.git_operations import checkout_commit, clean_repo

logger = get_logger(__name__)

__all__ = ["set_runtime_version", "setup_repo_prebuild"]

# Offset from BC platform major version to AL runtime version.
# E.g. platform 25.0 (BC 2024w2) → runtime 14.0, platform 27.0 → runtime 16.0
# See: BC-DeveloperExperience RuntimeVersion.cs
_PLATFORM_TO_RUNTIME_OFFSET = 11


def setup_repo_prebuild(entry: BaseDatasetEntry, repo_path: Path) -> None:
    """Setup repository before building - clean and checkout base commit.

    This is the first phase of repo setup that should be called BEFORE build_and_publish_projects.
    It prepares a clean slate at the base commit without any patches or problem statements.
    Skips for entries without a base_commit (e.g. categories that start from a blank project).

    Args:
        entry: Dataset entry with instance metadata
        repo_path: Path to the repository
    """
    if not entry.base_commit:
        logger.info(f"Skipping prebuild setup for {entry.instance_id} (no base_commit)")
        return

    clean_repo(repo_path)
    checkout_commit(repo_path, entry.base_commit)


def set_runtime_version(repo_path: Path, project_paths: list[str]) -> None:
    """Set the AL runtime version in each project's app.json based on platform version.

    The AL compiler (altool) defaults to the latest runtime, enabling newer validation rules that reject older code.
    Setting the runtime to match the platform version makes the compiler behave like the version that originally compiled the code.

    Can be skipped when altool is not used.
    """
    for project_path in project_paths:
        app_json_path = repo_path / project_path / "app.json"
        if not app_json_path.is_file():
            continue

        try:
            app_json = json.loads(app_json_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            continue

        if app_json.get("runtime"):
            continue

        platform: str = app_json.get("platform", "")
        try:
            platform_major = int(platform.split(".")[0])
        except (ValueError, IndexError):
            continue

        runtime_major: int = platform_major - _PLATFORM_TO_RUNTIME_OFFSET
        if runtime_major < 1:
            continue

        runtime: str = f"{runtime_major}.0"
        app_json["runtime"] = runtime
        app_json_path.write_text(json.dumps(app_json, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Set runtime={runtime} in {app_json_path} (platform {platform})")
