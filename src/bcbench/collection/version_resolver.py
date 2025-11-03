"""Utilities for determining environment setup versions."""

import json
import subprocess

from bcbench.config import get_config
from bcbench.logger import get_logger

logger = get_logger(__name__)


def determine_environment_setup_version(commit: str) -> str:
    """Determine the appropriate environment setup version based on commit availability in release branches."""
    config = get_config()

    try:
        result = subprocess.run(
            ["git", "show", "master:Directory.App.Props.json"],
            cwd=config.paths.nav_repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to retrieve Directory.App.Props.json: {e.stderr}")
        raise

    props_data = json.loads(result.stdout)
    current_version_str = props_data["variables"]["app_currentVersion"]
    current_major_version = int(current_version_str.split(".")[0])

    start_version = current_major_version - 1

    for major_version in range(start_version, 20, -1):
        for minor_version in [5, 4, 3, 2, 1, 0]:
            branch_name = f"releases/{major_version}.{minor_version}"

            try:
                subprocess.run(
                    [
                        "git",
                        "show-ref",
                        "--verify",
                        f"refs/remotes/origin/{branch_name}",
                    ],
                    cwd=config.paths.nav_repo_path,
                    capture_output=True,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                logger.debug(f"Failed to check branch existence for {branch_name}: {e.stderr}")
                continue

            try:
                subprocess.run(
                    [
                        "git",
                        "merge-base",
                        "--is-ancestor",
                        commit,
                        f"origin/{branch_name}",
                    ],
                    cwd=config.paths.nav_repo_path,
                    capture_output=True,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                logger.debug(f"Commit {commit} is not in branch {branch_name}: {e.stderr}")
                continue

            return f"{major_version}.{minor_version}"

    logger.warning(f"Could not determine environment setup version for commit {commit}")
    return ""
