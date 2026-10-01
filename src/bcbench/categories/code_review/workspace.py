import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from bcbench_core import git

from bcbench.categories.code_review.entry import CodeReviewEntry


def setup_workspace(
    entry: CodeReviewEntry,
    repo_path: Path,
    *,
    env: Mapping[str, str],
    remote: str,
    author_name: str,
    author_email: str,
    normalize_tables: Callable[[Path, list[str]], int],
) -> None:
    git.fetch_commit_if_missing(repo_path, entry.base_commit, remote=remote, env=env)
    git.clean_repo(repo_path, env=env)
    git.checkout_commit(repo_path, entry.base_commit, env=env)
    if removed_count := normalize_tables(repo_path, entry.project_paths):
        git.commit_changes(
            repo_path,
            f"Remove {removed_count} Scope = OnPrem declaration(s)",
            stage_pathspecs=(".",),
            author_name=author_name,
            author_email=author_email,
            env=env,
        )
    git.apply_patch(repo_path, entry.patch, f"{entry.instance_id} review patch", env=env)
    # Intent-to-add makes new files visible to the agent's git diff without staging the patch.
    if paths := [line[6:].strip() for line in entry.patch.splitlines() if line.startswith("+++ b/")]:
        subprocess.run(
            ["git", "add", "-N", "--", *paths],
            cwd=repo_path,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )
