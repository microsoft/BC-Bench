"""Git repository operations."""

import os
import stat
import subprocess
import tempfile
from pathlib import Path

from bcbench.config import get_config
from bcbench.exceptions import EmptyDiffError, GeneratedSubmissionError, GitOperationError, PatchApplicationError
from bcbench.logger import get_logger
from bcbench.operations.filesystem_operations import remove_tree

logger = get_logger(__name__)
_config = get_config()
_NULL_DEVICE = "NUL" if os.name == "nt" else "/dev/null"


def clean_repo(repo_path: Path) -> None:
    """Clean the repository by discarding all changes, including staged files and untracked files."""
    logger.info(f"Cleaning repository: {repo_path}")
    subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    subprocess.run(["git", "clean", "-fd"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    logger.info("Repository cleaned successfully")


def clean_project_paths(repo_path: Path, project_paths: list[str]) -> None:
    """Clean specific project paths by unstaging and discarding all changes in those directories.

    This function first unstages any staged changes in the specified paths, then reverts
    modified files and removes untracked files. This is useful when agents make unintended
    changes to projects they shouldn't touch (e.g., test files in bugfix, app files in testgen).

    Args:
        repo_path: Path to the git repository
        project_paths: List of relative project paths to clean

    Raises:
        subprocess.CalledProcessError: If git operations fail
    """
    if not project_paths:
        logger.error("No project paths provided to clean")
        raise ValueError("No project paths provided to clean")

    logger.info(f"Cleaning project paths: {project_paths}")

    # First, unstage any staged changes in these paths
    for project_path in project_paths:
        subprocess.run(["git", "reset", "HEAD", "--", project_path], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    # Then revert modified files in these paths
    subprocess.run(["git", "checkout", "HEAD", "--", *project_paths], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    # Finally, remove untracked files in these paths
    for project_path in project_paths:
        subprocess.run(["git", "clean", "-fd", project_path], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

    logger.info(f"Project paths cleaned successfully: {project_paths}")


def checkout_commit(repo_path: Path, commit: str) -> None:
    logger.info(f"Checking out commit: {commit}")
    subprocess.run(["git", "checkout", commit], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    logger.info(f"Commit {commit} checked out")


def _commit_present(repo_path: Path, commit: str) -> bool:
    result = subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return result.returncode == 0


def fetch_commit_if_missing(repo_path: Path, commit: str) -> None:
    """Fetch `commit` from origin when it is not already present in `repo_path`.

    Needed in local dev, might lack base commits that were squashed away on merge. No-op in CI, where the testbed is cloned at the exact commit already.
    """
    if _commit_present(repo_path, commit):
        return

    logger.info(f"Commit {commit} not present locally; fetching from origin")
    subprocess.run(["git", "fetch", "origin", commit], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    logger.info(f"Commit {commit} fetched")


def init_repo(repo_path: Path) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)


def has_changes(repo_path: Path) -> bool:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, capture_output=True, encoding="utf-8", text=True, check=True)
    return bool(result.stdout.strip())


def commit_changes(repo_path: Path, message: str, *, allow_empty: bool = False, no_verify: bool = False) -> None:
    logger.info(f"Committing changes: {message}")
    subprocess.run(["git", "add", "-A"], cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
    commit_args = ["git", "-c", "user.name=bcbench", "-c", "user.email=bcbench@noreply", "commit"]
    if allow_empty:
        commit_args.append("--allow-empty")
    if no_verify:
        commit_args.append("--no-verify")
    commit_args.extend(["-m", message])
    subprocess.run(
        commit_args,
        cwd=repo_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=True,
    )
    logger.info("Changes committed")


def apply_patch(repo_path: Path, patch_content: str, patch_name: str = "patch") -> None:
    logger.info(f"Applying {patch_name}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=_config.file_patterns.patch_pattern, delete=False, encoding="utf-8") as f:
        f.write(patch_content)
        patch_file = f.name

    try:
        subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "--ignore-whitespace", patch_file],
            cwd=repo_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            text=True,
            check=True,
        )

        logger.info(f"{patch_name.capitalize()} applied successfully")
    except subprocess.CalledProcessError as e:
        logger.exception(f"{patch_name.capitalize()} application failed: {e.stderr}")
        raise PatchApplicationError(patch_name, e.stderr) from e
    finally:
        Path(patch_file).unlink(missing_ok=True)


def stage_and_get_diff(repo_path: Path) -> str:
    """Stage all *.al file changes and get the git diff.

    This function stages all *.al files in the repository and returns the diff.
    It does NOT stage app.json files as dataset doesn't include app.json changes yet.

    Args:
        repo_path: Path to the git repository

    Returns:
        String containing the git diff patch

    Raises:
        EmptyDiffError: If the generated diff is empty (agent made no changes)
    """
    logger.info("Staging *.al file changes and getting git diff")

    # Stage all changes, so new files can be captured in the diff (only *.al files for now).
    # A missing-pathspec error (exit 128) means the agent produced no *.al files at all -> empty diff.
    # Any other failure is a real git error and propagates to fail the job.
    try:
        subprocess.run(["git", "add", "*.al"], cwd=repo_path, capture_output=True, encoding="utf-8", text=True, check=True)
    except subprocess.CalledProcessError as e:
        if e.stderr and "did not match" in e.stderr:
            logger.warning("No *.al files produced by agent - treating as empty diff")
            raise EmptyDiffError from e
        raise

    # Get diff of staged changes against HEAD
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", "diff", "--cached", "--", ".", ":!*.docx", ":!**/app.json", ":!*.md"],
        cwd=repo_path,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    )
    patch: str = result.stdout
    logger.info("Git diff retrieved successfully")
    logger.debug(f"Generated diff:\n{patch}")

    if not patch:
        logger.error("Generated diff is empty - agent made no changes")
        raise EmptyDiffError

    return patch


def _sanitized_git_environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update(
        {
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": _NULL_DEVICE,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def _is_reparse_point(path_stat: os.stat_result) -> bool:
    return bool(getattr(path_stat, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _validate_workspace_for_freeze(repo_path: Path) -> tuple[Path, tuple[tuple[Path, os.stat_result], ...]]:
    try:
        repo_stat = repo_path.lstat()
        if repo_path.is_symlink() or _is_reparse_point(repo_stat):
            raise GeneratedSubmissionError(f"Cannot safely freeze workspace symbolic link or reparse point: {repo_path}")
        workspace_path = repo_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise GeneratedSubmissionError(f"Cannot safely freeze workspace: {repo_path}: {exc}") from exc

    pending_directories = [workspace_path]
    regular_files: list[tuple[Path, os.stat_result]] = []
    while pending_directories:
        directory_path = pending_directories.pop()
        try:
            with os.scandir(directory_path) as directory_entries:
                entries = tuple(directory_entries)
        except OSError as exc:
            raise GeneratedSubmissionError(f"Cannot safely inspect workspace directory: {directory_path}: {exc}") from exc

        for entry in entries:
            entry_path = Path(entry.path)
            relative_path = entry_path.relative_to(workspace_path)
            if len(relative_path.parts) == 1 and entry.name.casefold() == ".git":
                continue
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise GeneratedSubmissionError(f"Cannot safely inspect workspace entry: {relative_path}: {exc}") from exc

            if entry.is_symlink() or _is_reparse_point(entry_stat):
                raise GeneratedSubmissionError(f"Cannot safely freeze workspace symbolic link or reparse point: {relative_path}")
            if len(relative_path.parts) > 1 and entry.name.casefold() == ".git":
                raise GeneratedSubmissionError(f"Cannot safely freeze nested Git administrative entry: {relative_path}")

            try:
                resolved_entry_path = entry_path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise GeneratedSubmissionError(f"Cannot safely resolve workspace entry: {relative_path}: {exc}") from exc
            if not resolved_entry_path.is_relative_to(workspace_path):
                raise GeneratedSubmissionError(f"Cannot safely freeze workspace entry outside workspace: {relative_path}")

            if entry.is_dir(follow_symlinks=False):
                pending_directories.append(entry_path)
            elif stat.S_ISREG(entry_stat.st_mode):
                regular_files.append((relative_path, entry_stat))
            else:
                raise GeneratedSubmissionError(f"Cannot safely freeze unsupported workspace entry: {relative_path}")

    return workspace_path, tuple(regular_files)


def _resolve_source_object_directory(repo_path: Path, environment: dict[str, str]) -> Path:
    result = subprocess.run(
        ["git", "--no-replace-objects", "rev-parse", "--path-format=absolute", "--git-path", "objects"],
        cwd=repo_path,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    )
    unresolved_object_directory = Path(result.stdout.strip())
    try:
        object_directory_stat = unresolved_object_directory.lstat()
    except OSError as exc:
        raise GitOperationError(f"Cannot inspect Git object directory: {unresolved_object_directory}: {exc}") from exc
    if unresolved_object_directory.is_symlink() or _is_reparse_point(object_directory_stat):
        raise GeneratedSubmissionError(f"Cannot safely freeze Git object directory symbolic link or reparse point: {unresolved_object_directory}")

    object_directory = unresolved_object_directory.resolve(strict=True)
    if not object_directory.is_dir():
        raise GitOperationError(f"Git object directory is not a directory: {object_directory}")
    if not object_directory.is_relative_to(repo_path):
        raise GeneratedSubmissionError(f"Cannot safely freeze Git object directory outside workspace: {object_directory}")
    return object_directory


def resolve_trusted_commit(repo_path: Path, trusted_commit: str, *, environment: dict[str, str] | None = None) -> str:
    if not trusted_commit:
        raise GitOperationError("Trusted baseline revision is missing.")

    result = subprocess.run(
        ["git", "--no-replace-objects", "rev-parse", "--verify", "--end-of-options", f"{trusted_commit}^{{commit}}"],
        cwd=repo_path,
        env=environment or _sanitized_git_environment(),
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitOperationError(f"Trusted baseline revision does not resolve to a commit: {trusted_commit}")
    return result.stdout.strip()


def _trusted_tree_modes(repo_path: Path, trusted_commit: str, environment: dict[str, str]) -> dict[bytes, bytes]:
    result = subprocess.run(
        ["git", "--no-replace-objects", "ls-tree", "-r", "-z", trusted_commit],
        cwd=repo_path,
        env=environment,
        capture_output=True,
        check=True,
    )
    modes: dict[bytes, bytes] = {}
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, path = entry.split(b"\t", maxsplit=1)
        mode, _object_type, _object_id = metadata.split(b" ", maxsplit=2)
        modes[path] = mode
    return modes


def _workspace_git_path(relative_path: Path) -> bytes:
    git_path = os.fsencode(relative_path.as_posix())
    if b"\n" in git_path or b"\r" in git_path:
        raise GeneratedSubmissionError(f"Cannot safely snapshot workspace path containing a line break: {relative_path}")
    return git_path


def _new_file_mode(path_stat: os.stat_result) -> bytes:
    if os.name == "nt" or not path_stat.st_mode & stat.S_IXUSR:
        return b"100644"
    return b"100755"


def _populate_raw_submission_index(
    git_command: list[str],
    workspace_path: Path,
    regular_files: tuple[tuple[Path, os.stat_result], ...],
    trusted_modes: dict[bytes, bytes],
    environment: dict[str, str],
) -> None:
    snapshot_files = sorted(
        ((_workspace_git_path(relative_path), path_stat) for relative_path, path_stat in regular_files),
        key=lambda item: item[0],
    )
    paths_input = b"".join(path + b"\n" for path, _path_stat in snapshot_files)
    try:
        hash_result = subprocess.run(
            [*git_command, "hash-object", "-w", "--no-filters", "--stdin-paths"],
            cwd=workspace_path,
            env=environment,
            input=paths_input,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        error = exc.stderr.decode("utf-8", errors="replace").strip()
        message = "Cannot snapshot generated workspace files as raw Git blobs."
        if error:
            message = f"{message} {error}"
        raise GeneratedSubmissionError(message) from exc

    object_ids = hash_result.stdout.splitlines()
    if len(object_ids) != len(snapshot_files):
        raise GeneratedSubmissionError(f"Cannot snapshot generated workspace files as raw Git blobs: expected {len(snapshot_files)} object IDs, received {len(object_ids)}.")

    index_entries = b"".join(
        (trusted_modes.get(path, _new_file_mode(path_stat)) + b" blob " + object_id + b"\t" + path + b"\0") for (path, path_stat), object_id in zip(snapshot_files, object_ids, strict=True)
    )
    subprocess.run(
        [*git_command, "read-tree", "--empty"],
        cwd=workspace_path,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=True,
    )
    try:
        subprocess.run(
            [*git_command, "update-index", "--add", "-z", "--index-info"],
            cwd=workspace_path,
            env=environment,
            input=index_entries,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        error = exc.stderr.decode("utf-8", errors="replace").strip()
        message = "Cannot construct generated submission index from raw workspace files."
        if error:
            message = f"{message} {error}"
        raise GeneratedSubmissionError(message) from exc


def stage_and_get_complete_diff(repo_path: Path, trusted_commit: str) -> str:
    """Freeze every safe workspace change and return the complete binary-safe diff."""
    workspace_path, regular_files = _validate_workspace_for_freeze(repo_path)
    git_environment = _sanitized_git_environment()
    source_object_directory = _resolve_source_object_directory(workspace_path, git_environment)
    resolved_trusted_commit = resolve_trusted_commit(workspace_path, trusted_commit, environment=git_environment)
    trusted_modes = _trusted_tree_modes(workspace_path, resolved_trusted_commit, git_environment)
    logger.info("Staging all changes and getting complete git diff")
    temporary_git_root = Path(tempfile.mkdtemp(prefix="bcbench-submission-freeze-"))
    try:
        git_directory = temporary_git_root / "git"
        hooks_directory = temporary_git_root / "hooks"
        template_directory = temporary_git_root / "template"
        hooks_directory.mkdir()
        template_directory.mkdir()
        subprocess.run(
            ["git", "init", "--bare", "--quiet", f"--template={template_directory}", str(git_directory)],
            cwd=temporary_git_root,
            env=git_environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )
        (git_directory / "objects" / "info" / "alternates").write_bytes(f"{source_object_directory.as_posix()}\n".encode())
        subprocess.run(
            ["git", f"--git-dir={git_directory}", "config", "core.hooksPath", str(hooks_directory)],
            cwd=temporary_git_root,
            env=git_environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )
        git_command = [
            "git",
            "--no-replace-objects",
            f"--git-dir={git_directory}",
            f"--work-tree={workspace_path}",
            "-c",
            "core.autocrlf=true",
            "-c",
            f"core.excludesFile={_NULL_DEVICE}",
        ]
        _populate_raw_submission_index(git_command, workspace_path, regular_files, trusted_modes, git_environment)
        result = subprocess.run(
            [*git_command, "-c", "core.quotePath=false", "diff", "--cached", resolved_trusted_commit, "--binary", "--no-ext-diff"],
            cwd=workspace_path,
            env=git_environment,
            capture_output=True,
            check=True,
        )
        patch_bytes: bytes = result.stdout
    finally:
        remove_tree(temporary_git_root)

    if patch_bytes == b"":
        logger.error("Generated complete diff is empty - agent made no changes")
        raise EmptyDiffError

    try:
        patch = patch_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GeneratedSubmissionError("Generated submission diff is not valid UTF-8.") from exc

    logger.info("Complete git diff retrieved successfully")
    logger.debug(f"Generated complete diff:\n{patch}")

    return patch


def clone_repo_at_revision(repo: str, revision: str, destination: Path) -> None:
    """Shallow-clone `repo` at a specific `revision` into `destination`.

    Uses `gh repo clone`, so the GitHub CLI resolves the URL and handles authentication,
    while `git clone --revision` checks the revision out directly.

    Args:
        repo: A GitHub `owner/repo` slug.
        revision: A commit SHA.
        destination: Target directory, replaced if it already exists.

    Note:
        `git clone --revision` requires git 2.49+.
    """
    logger.info(f"Cloning {repo} @ {revision} into {destination}")
    if destination.exists():
        remove_tree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            ["gh", "repo", "clone", repo, str(destination), "--", "--depth=1", f"--revision={revision}"],
            capture_output=True,
            encoding="utf-8",
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.exception(f"Cloning {repo} @ {revision} failed: {e.stderr}")
        raise

    logger.info(f"Cloned {repo} @ {revision}")
