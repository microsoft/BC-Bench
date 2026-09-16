import os
import subprocess
from pathlib import Path
from uuid import uuid4

from bcbench.evaluate.bugfix_lifecycle.models import BugFixLifecyclePaths, TrustedSource
from bcbench.operations.filesystem_operations import remove_tree

_MANAGED_PATH_NAMES = (
    "baseline_workspace",
    "agent_workspace",
    "agent_logs",
    "mounted_staging",
    "evaluator_workspaces",
    "evidence",
    "protected_root",
    "checkpoints",
    "final_results",
)
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            environment.pop(name)
    for name in (
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CONFIG_COUNT",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_REPLACE_REF_BASE",
        "GIT_WORK_TREE",
    ):
        environment.pop(name, None)
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
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


def _is_reparse_point(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _reject_reparse_components(path: Path, root: Path) -> None:
    absolute_path = path.absolute()
    absolute_root = root.absolute()
    try:
        relative_path = absolute_path.relative_to(absolute_root)
    except ValueError:
        return

    current = absolute_root
    if _is_reparse_point(current):
        raise ValueError(f"Refusing symbolic link or reparse point: {current}")
    for part in relative_path.parts:
        if part == "..":
            return
        current /= part
        if _is_reparse_point(current):
            raise ValueError(f"Refusing symbolic link or reparse point: {current}")


def _require_strict_child(path: Path, root: Path, root_name: str) -> Path:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_path == resolved_root or not resolved_path.is_relative_to(resolved_root):
        raise ValueError(f"{path} must resolve below {root_name} {resolved_root}")
    return resolved_path


def _safe_workspace_name(name: str) -> str:
    reserved_stem = name.partition(".")[0].upper()
    if not name or name in {".", ".."} or name.endswith((" ", ".")) or any(character in name for character in ("/", "\\", ":", "\0")) or reserved_stem in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"Invalid evaluator workspace name: {name!r}")
    return name


class TrustedWorkspaceBuilder:
    def __init__(self, paths: BugFixLifecyclePaths) -> None:
        self._paths = paths
        _reject_reparse_components(paths.entry_root, paths.entry_root)
        self._entry_root = paths.entry_root.resolve()
        if self._entry_root == Path(self._entry_root.anchor):
            raise ValueError("entry_root cannot be a filesystem root")

        self._managed_paths = {}
        for name in _MANAGED_PATH_NAMES:
            managed_path = getattr(paths, name)
            _reject_reparse_components(managed_path, paths.entry_root)
            self._managed_paths[name] = _require_strict_child(managed_path, self._entry_root, "entry_root")
        _reject_reparse_components(paths.trusted_source, paths.protected_root)
        self._trusted_source = _require_strict_child(paths.trusted_source, self._managed_paths["protected_root"], "protected_root")

    def capture_trusted_source(self, baseline: Path) -> TrustedSource:
        _reject_reparse_components(baseline, self._paths.entry_root)
        resolved_baseline = _require_strict_child(baseline, self._entry_root, "entry_root")
        if resolved_baseline != self._managed_paths["baseline_workspace"]:
            raise ValueError("Baseline must match the managed baseline_workspace")
        if not resolved_baseline.is_dir():
            raise ValueError(f"Baseline workspace does not exist: {baseline}")
        if self._trusted_source.exists():
            raise FileExistsError(f"Trusted source already exists: {self._trusted_source}")

        commit = _run_git(["rev-parse", "--verify", "HEAD^{commit}"], cwd=resolved_baseline)
        self._trusted_source.parent.mkdir(parents=True, exist_ok=True)
        _run_git(
            [
                "clone",
                "--bare",
                "--no-local",
                "--no-hardlinks",
                "--no-tags",
                str(resolved_baseline),
                str(self._trusted_source),
            ]
        )
        _run_git([f"--git-dir={self._trusted_source}", "cat-file", "-e", f"{commit}^{{commit}}"])
        return TrustedSource(repository=self._trusted_source, commit=commit)

    def create_agent_workspace(self, trusted_source: TrustedSource) -> Path:
        destination = self._managed_paths["agent_workspace"]
        self._clone_trusted_commit(trusted_source, destination)
        return destination

    def create_evaluator_workspace(self, trusted_source: TrustedSource, name: str) -> Path:
        safe_name = _safe_workspace_name(name)
        evaluator_root = self._managed_paths["evaluator_workspaces"]
        destination = evaluator_root / f"{safe_name}-{uuid4().hex}"
        _require_strict_child(destination, evaluator_root, "evaluator_workspaces")
        self._clone_trusted_commit(trusted_source, destination)
        return destination

    def remove_baseline_workspace(self) -> None:
        baseline = self._managed_paths["baseline_workspace"]
        _reject_reparse_components(baseline, self._entry_root)
        _require_strict_child(baseline, self._entry_root, "entry_root")
        if not baseline.exists():
            return
        if not baseline.is_dir():
            raise ValueError(f"Baseline workspace is not a directory: {baseline}")
        remove_tree(baseline)

    def _clone_trusted_commit(self, trusted_source: TrustedSource, destination: Path) -> None:
        repository = trusted_source.repository.resolve()
        if repository != self._trusted_source:
            raise ValueError("Trusted repository does not match the protected trusted source")
        if destination.exists():
            raise FileExistsError(f"Workspace already exists: {destination}")
        _reject_reparse_components(destination, self._entry_root)
        _require_strict_child(destination, self._entry_root, "entry_root")

        destination.parent.mkdir(parents=True, exist_ok=True)
        _run_git(
            [
                "clone",
                "--no-local",
                "--no-hardlinks",
                "--no-checkout",
                str(repository),
                str(destination),
            ]
        )
        _run_git(["checkout", "--detach", trusted_source.commit], cwd=destination)
        checked_out_commit = _run_git(["rev-parse", "--verify", "HEAD^{commit}"], cwd=destination)
        if checked_out_commit != trusted_source.commit:
            raise ValueError(f"Workspace checkout mismatch: expected {trusted_source.commit}, got {checked_out_commit}")
