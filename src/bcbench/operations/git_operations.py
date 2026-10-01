"""Git operations with the application's staging, identity, and authentication policy."""

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from bcbench_core import git

from bcbench.logger import get_logger
from bcbench.operations.filesystem_operations import remove_tree

logger = get_logger(__name__)


def clean_repo(repo_path: Path, *, env: Mapping[str, str] | None = None) -> None:
    git.clean_repo(repo_path, env=env if env is not None else os.environ)


def clean_project_paths(repo_path: Path, project_paths: list[str], *, env: Mapping[str, str] | None = None) -> None:
    git.clean_project_paths(repo_path, project_paths, env=env if env is not None else os.environ)


def checkout_commit(repo_path: Path, commit: str, *, env: Mapping[str, str] | None = None) -> None:
    git.checkout_commit(repo_path, commit, env=env if env is not None else os.environ)


def fetch_commit_if_missing(repo_path: Path, commit: str, *, env: Mapping[str, str] | None = None) -> None:
    git.fetch_commit_if_missing(repo_path, commit, remote="origin", env=env if env is not None else os.environ)


def init_repo(repo_path: Path, *, env: Mapping[str, str] | None = None) -> None:
    git.init_repo(repo_path, env=env if env is not None else os.environ)


def has_changes(repo_path: Path, *, env: Mapping[str, str] | None = None) -> bool:
    return git.has_changes(repo_path, env=env if env is not None else os.environ)


def commit_changes(repo_path: Path, message: str, *, allow_empty: bool = False, no_verify: bool = False, env: Mapping[str, str] | None = None) -> None:
    git.commit_changes(
        repo_path,
        message,
        stage_pathspecs=(".",),
        author_name="bcbench",
        author_email="bcbench@noreply",
        env=env if env is not None else os.environ,
        allow_empty=allow_empty,
        no_verify=no_verify,
    )


def apply_patch(repo_path: Path, patch_content: str, patch_name: str = "patch", *, env: Mapping[str, str] | None = None) -> None:
    git.apply_patch(repo_path, patch_content, patch_name, env=env if env is not None else os.environ)


def stage_and_get_diff(repo_path: Path, *, env: Mapping[str, str] | None = None) -> str:
    """Stage AL file changes, excluding manifests and documentation from the diff."""
    return git.stage_and_get_diff(
        repo_path,
        stage_pathspecs=("*.al",),
        diff_excludes=("*.docx", "**/app.json", "*.md"),
        env=env if env is not None else os.environ,
    )


def clone_repo_at_revision(repo: str, revision: str, destination: Path, *, env: Mapping[str, str], executable: str) -> None:
    """Shallow-clone a revision with GitHub CLI authentication (requires git 2.49+)."""
    logger.info(f"Cloning {repo} @ {revision} into {destination}")
    if destination.exists():
        remove_tree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            [executable, "repo", "clone", repo, str(destination), "--", "--depth=1", f"--revision={revision}"],
            env=dict(env),
            capture_output=True,
            encoding="utf-8",
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.exception(f"Cloning {repo} @ {revision} failed: {e.stderr}")
        raise

    logger.info(f"Cloned {repo} @ {revision}")
