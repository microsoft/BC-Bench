import os
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from bcbench.evaluate.bugfix_lifecycle.models import BugFixLifecyclePaths, TrustedSource
from bcbench.evaluate.bugfix_lifecycle.path_safety import (
    ENTRY_MANAGED_PATH_NAMES,
    absolute_path,
    reject_reparse_components,
    require_strict_descendant,
    validate_lifecycle_paths,
)
from bcbench.operations.filesystem_operations import remove_tree

_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _git_environment() -> dict[str, str]:
    environment = {name: value for name, value in os.environ.items() if not name.upper().startswith("GIT_")}
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def _run_git(arguments: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", "--no-replace-objects", *arguments],
        cwd=cwd,
        env=_git_environment(),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def materialized_workspace_tree_hash(workspace: Path) -> str:
    resolved_workspace = workspace.resolve()
    git_directory = resolved_workspace / ".git"
    if not resolved_workspace.is_dir() or not git_directory.is_dir():
        raise ValueError(f"Evaluator workspace must be a Git repository: {workspace}")

    with tempfile.NamedTemporaryFile(
        prefix="bcbench-index-",
        dir=git_directory,
        delete=False,
    ) as temporary_index:
        index_path = Path(temporary_index.name)
    index_path.unlink()
    environment = _git_environment()
    environment["GIT_INDEX_FILE"] = str(index_path)
    git_prefix = [
        "git",
        "--no-replace-objects",
        "-c",
        f"core.attributesFile={os.devnull}",
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.safecrlf=false",
    ]
    excluded_paths = (
        ":(exclude,glob)**/output/**",
        ":(exclude,glob)**/.alpackages/**",
        ":(exclude,glob)**/evidence/**",
    )
    try:
        subprocess.run(
            [*git_prefix, "read-tree", "--empty"],
            cwd=resolved_workspace,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        subprocess.run(
            [*git_prefix, "add", "--all", "--force", "--", ".", *excluded_paths],
            cwd=resolved_workspace,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = subprocess.run(
            [*git_prefix, "write-tree"],
            cwd=resolved_workspace,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip()
    finally:
        index_path.unlink(missing_ok=True)


def _safe_workspace_name(name: str) -> str:
    reserved_stem = name.partition(".")[0].upper()
    if not name or name in {".", ".."} or name.endswith((" ", ".")) or any(character in name for character in ("/", "\\", ":", "\0")) or reserved_stem in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"Invalid evaluator workspace name: {name!r}")
    return name


class TrustedWorkspaceBuilder:
    def __init__(self, paths: BugFixLifecyclePaths) -> None:
        self._paths = validate_lifecycle_paths(paths)
        self._entry_root = self._paths.entry_root
        self._protected_root = self._paths.protected_root
        self._managed_paths = {name: getattr(self._paths, name) for name in ENTRY_MANAGED_PATH_NAMES}
        self._trusted_source = self._paths.trusted_source
        self._captured_source: TrustedSource | None = None

    @contextmanager
    def _empty_git_template(self) -> Iterator[Path]:
        self._protected_root.mkdir(parents=True, exist_ok=True)
        reject_reparse_components(self._protected_root, self._protected_root)
        with tempfile.TemporaryDirectory(prefix=".git-template-", dir=self._protected_root) as temporary_directory:
            template = Path(temporary_directory)
            reject_reparse_components(template, self._protected_root)
            yield template

    def capture_trusted_source(self, baseline: Path) -> TrustedSource:
        reject_reparse_components(baseline, self._entry_root)
        resolved_baseline = require_strict_descendant(baseline, self._entry_root, "baseline", "entry_root")
        if resolved_baseline != self._managed_paths["baseline_workspace"]:
            raise ValueError("Baseline must match the managed baseline_workspace")
        if not resolved_baseline.is_dir():
            raise ValueError(f"Baseline workspace does not exist: {baseline}")
        if self._trusted_source.exists():
            raise FileExistsError(f"Trusted source already exists: {self._trusted_source}")

        commit = _run_git(["rev-parse", "--verify", "HEAD^{commit}"], cwd=resolved_baseline)
        self._trusted_source.parent.mkdir(parents=True, exist_ok=True)
        reject_reparse_components(self._trusted_source, self._protected_root)
        with self._empty_git_template() as template:
            _run_git(
                [
                    "clone",
                    f"--template={template}",
                    "--bare",
                    "--no-local",
                    "--no-hardlinks",
                    "--no-tags",
                    str(resolved_baseline),
                    str(self._trusted_source),
                ]
            )
        _run_git([f"--git-dir={self._trusted_source}", "cat-file", "-e", f"{commit}^{{commit}}"])
        self._captured_source = TrustedSource(repository=self._trusted_source, commit=commit)
        return self._captured_source

    def create_agent_workspace(self, trusted_source: TrustedSource) -> Path:
        destination = self._managed_paths["agent_workspace"]
        self._clone_trusted_commit(trusted_source, destination)
        return destination

    def create_evaluator_workspace(self, trusted_source: TrustedSource, name: str) -> Path:
        safe_name = _safe_workspace_name(name)
        evaluator_root = self._managed_paths["evaluator_workspaces"]
        destination = evaluator_root / f"{safe_name}-{uuid4().hex}"
        require_strict_descendant(destination, evaluator_root, "destination", "evaluator_workspaces")
        self._clone_trusted_commit(trusted_source, destination)
        return destination

    def remove_baseline_workspace(self) -> None:
        baseline = self._managed_paths["baseline_workspace"]
        reject_reparse_components(baseline, self._entry_root)
        require_strict_descendant(baseline, self._entry_root, "baseline_workspace", "entry_root")
        if not baseline.exists():
            return
        if not baseline.is_dir():
            raise ValueError(f"Baseline workspace is not a directory: {baseline}")
        remove_tree(baseline)

    def _clone_trusted_commit(self, trusted_source: TrustedSource, destination: Path) -> None:
        if self._captured_source is None:
            raise ValueError("Trusted source has not been captured")
        repository = absolute_path(trusted_source.repository)
        if repository != self._captured_source.repository:
            raise ValueError("Trusted repository does not match the protected trusted source")
        if trusted_source.commit != self._captured_source.commit:
            raise ValueError("Trusted commit does not match the captured trusted source")
        reject_reparse_components(repository, self._protected_root)
        if destination.exists():
            raise FileExistsError(f"Workspace already exists: {destination}")
        reject_reparse_components(destination, self._entry_root)
        require_strict_descendant(destination, self._entry_root, "destination", "entry_root")

        destination.parent.mkdir(parents=True, exist_ok=True)
        reject_reparse_components(destination, self._entry_root)
        with self._empty_git_template() as template:
            _run_git(
                [
                    "clone",
                    f"--template={template}",
                    "--no-local",
                    "--no-hardlinks",
                    "--no-checkout",
                    str(repository),
                    str(destination),
                ]
            )
        reject_reparse_components(destination, self._entry_root)
        _run_git(["checkout", "--detach", self._captured_source.commit], cwd=destination)
        checked_out_commit = _run_git(["rev-parse", "--verify", "HEAD^{commit}"], cwd=destination)
        if checked_out_commit != self._captured_source.commit:
            raise ValueError(f"Workspace checkout mismatch: expected {self._captured_source.commit}, got {checked_out_commit}")
