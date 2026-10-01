import logging
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from bcbench_core.exceptions import EmptyDiffError, PatchApplicationError

logger = logging.getLogger(__name__)


def clean_repo(repo_path: Path, *, env: Mapping[str, str]) -> None:
    logger.info("Cleaning repository: %s", repo_path)
    subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=repo_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    subprocess.run(["git", "clean", "-fd"], cwd=repo_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    logger.info("Repository cleaned successfully")


def clean_project_paths(repo_path: Path, project_paths: Sequence[str], *, env: Mapping[str, str]) -> None:
    if not project_paths:
        raise ValueError("No project paths provided to clean")

    logger.info("Cleaning project paths: %s", project_paths)
    for project_path in project_paths:
        subprocess.run(["git", "reset", "HEAD", "--", project_path], cwd=repo_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    subprocess.run(["git", "checkout", "HEAD", "--", *project_paths], cwd=repo_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    for project_path in project_paths:
        subprocess.run(["git", "clean", "-fd", "--", project_path], cwd=repo_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    logger.info("Project paths cleaned successfully: %s", project_paths)


def checkout_commit(repo_path: Path, commit: str, *, env: Mapping[str, str]) -> None:
    logger.info("Checking out commit: %s", commit)
    subprocess.run(["git", "checkout", commit], cwd=repo_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    logger.info("Commit %s checked out", commit)


def _commit_present(repo_path: Path, commit: str, *, env: Mapping[str, str]) -> bool:
    result = subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=repo_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return result.returncode == 0


def fetch_commit_if_missing(repo_path: Path, commit: str, *, remote: str, env: Mapping[str, str]) -> None:
    if _commit_present(repo_path, commit, env=env):
        return

    logger.info("Commit %s not present locally; fetching from %s", commit, remote)
    subprocess.run(["git", "fetch", remote, commit], cwd=repo_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    logger.info("Commit %s fetched", commit)


def init_repo(repo_path: Path, *, env: Mapping[str, str]) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)


def has_changes(repo_path: Path, *, env: Mapping[str, str]) -> bool:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, env=env, capture_output=True, encoding="utf-8", text=True, check=True)
    return bool(result.stdout.strip())


def commit_changes(
    repo_path: Path,
    message: str,
    *,
    stage_pathspecs: Sequence[str],
    author_name: str,
    author_email: str,
    env: Mapping[str, str],
    allow_empty: bool = False,
    no_verify: bool = False,
) -> None:
    logger.info("Committing changes: %s", message)
    if stage_pathspecs:
        subprocess.run(["git", "add", "-A", "--", *stage_pathspecs], cwd=repo_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    commit_args = ["git", "-c", f"user.name={author_name}", "-c", f"user.email={author_email}", "commit"]
    if allow_empty:
        commit_args.append("--allow-empty")
    if no_verify:
        commit_args.append("--no-verify")
    commit_args.extend(["-m", message])
    subprocess.run(commit_args, cwd=repo_path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    logger.info("Changes committed")


def apply_patch(repo_path: Path, patch_content: str, patch_name: str = "patch", *, env: Mapping[str, str]) -> None:
    logger.info("Applying %s", patch_name)
    try:
        subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "--ignore-whitespace", "-"],
            cwd=repo_path,
            env=env,
            input=patch_content,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.exception("%s application failed: %s", patch_name.capitalize(), e.stderr)
        raise PatchApplicationError(patch_name, e.stderr) from e
    logger.info("%s applied successfully", patch_name.capitalize())


def stage_and_get_diff(
    repo_path: Path,
    *,
    stage_pathspecs: Sequence[str],
    diff_excludes: Sequence[str],
    env: Mapping[str, str],
) -> str:
    if not stage_pathspecs:
        raise ValueError("No stage pathspecs provided")

    logger.info("Staging file changes for %s and getting git diff", stage_pathspecs)
    try:
        subprocess.run(["git", "add", "--", *stage_pathspecs], cwd=repo_path, env=env, capture_output=True, encoding="utf-8", text=True, check=True)
    except subprocess.CalledProcessError as e:
        if e.stderr and "did not match" in e.stderr:
            logger.warning("No files match the stage pathspecs")
            raise EmptyDiffError from e
        raise

    result = subprocess.run(
        ["git", "diff", "--cached", "--", ".", *(f":!{pattern}" for pattern in diff_excludes)],
        cwd=repo_path,
        env=env,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    )
    patch: str = result.stdout
    if not patch:
        raise EmptyDiffError
    logger.info("Git diff retrieved successfully")
    logger.debug("Generated diff:\n%s", patch)
    return patch
