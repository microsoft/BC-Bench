import os
import stat
from dataclasses import replace
from itertools import combinations
from pathlib import Path

from bcbench.evaluate.bugfix_lifecycle.models import (
    BugFixLifecyclePaths,
    OwnedLifecycleRoot,
    ProvisionedLifecycleResources,
)

ENTRY_MANAGED_PATH_NAMES = (
    "baseline_workspace",
    "agent_workspace",
    "agent_logs",
    "agent_tools",
    "mounted_staging",
    "evaluator_workspaces",
    "evidence",
)
PROTECTED_MANAGED_PATH_NAMES = (
    "trusted_source",
    "checkpoints",
    "final_results",
)


def absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path))  # noqa: PTH100 - resolving could traverse a reparse point before validation


def _path_components(path: Path) -> list[Path]:
    absolute = absolute_path(path)
    current = Path(absolute.anchor)
    components = [current]
    for part in absolute.parts[1:]:
        current /= part
        components.append(current)
    return components


def _canonical_path(path: Path) -> Path:
    absolute = absolute_path(path)
    for component in _path_components(absolute):
        if _is_reparse_point(component):
            raise ValueError(f"Refusing symbolic link or reparse point: {component}")
    return absolute.resolve()


def _is_same_or_ancestor(ancestor: Path, path: Path) -> bool:
    return path == ancestor or path.is_relative_to(ancestor)


def paths_overlap(first: Path, second: Path) -> bool:
    return _is_same_or_ancestor(first, second) or _is_same_or_ancestor(second, first)


def require_disjoint(first: Path, second: Path, first_name: str, second_name: str) -> None:
    canonical_first = _canonical_path(first)
    canonical_second = _canonical_path(second)
    if paths_overlap(canonical_first, canonical_second):
        raise ValueError(f"{first_name} and {second_name} must be disjoint")


def require_strict_descendant(path: Path, root: Path, path_name: str, root_name: str) -> Path:
    canonical_root = _canonical_path(root)
    canonical = _canonical_path(path)
    if canonical == canonical_root or not canonical.is_relative_to(canonical_root):
        raise ValueError(f"{path_name} {canonical} must be a strict descendant of {root_name} {canonical_root}")
    return canonical


def _is_reparse_point(path: Path) -> bool:
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return False
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(getattr(path_stat, "st_file_attributes", 0) & reparse_attribute)


def reject_reparse_components(path: Path, root: Path) -> None:
    canonical_root = _canonical_path(root)
    canonical = _canonical_path(path)
    if canonical != canonical_root and not canonical.is_relative_to(canonical_root):
        raise ValueError(f"{canonical} must be within {canonical_root}")


def _reject_overlaps(paths: dict[str, Path]) -> None:
    for (first_name, first), (second_name, second) in combinations(paths.items(), 2):
        if paths_overlap(first, second):
            raise ValueError(f"{first_name} and {second_name} must not contain each other")


def validate_evidence_roots(
    entry_root: Path,
    evidence: Path,
    protected_root: Path,
    final_results: Path,
) -> tuple[Path, Path, Path, Path]:
    absolute_entry = absolute_path(entry_root)
    absolute_protected = absolute_path(protected_root)
    if absolute_entry == Path(absolute_entry.anchor):
        raise ValueError("entry_root cannot be a filesystem root")
    if absolute_protected == Path(absolute_protected.anchor):
        raise ValueError("protected_root cannot be a filesystem root")
    require_disjoint(absolute_entry, absolute_protected, "entry_root", "protected_root")
    canonical_entry = _canonical_path(absolute_entry)
    canonical_protected = _canonical_path(absolute_protected)
    canonical_evidence = require_strict_descendant(evidence, canonical_entry, "evidence", "entry_root")
    canonical_final_results = require_strict_descendant(final_results, canonical_protected, "final_results", "protected_root")
    return canonical_entry, canonical_evidence, canonical_protected, canonical_final_results


def validate_lifecycle_paths(paths: BugFixLifecyclePaths) -> BugFixLifecyclePaths:
    entry_root, _, protected_root, _ = validate_evidence_roots(
        paths.entry_root,
        paths.evidence,
        paths.protected_root,
        paths.final_results,
    )

    entry_paths = {name: require_strict_descendant(getattr(paths, name), entry_root, name, "entry_root") for name in ENTRY_MANAGED_PATH_NAMES}
    protected_paths = {name: require_strict_descendant(getattr(paths, name), protected_root, name, "protected_root") for name in PROTECTED_MANAGED_PATH_NAMES}
    for path in entry_paths.values():
        reject_reparse_components(path, entry_root)
    for path in protected_paths.values():
        reject_reparse_components(path, protected_root)
    _reject_overlaps(entry_paths)
    _reject_overlaps(protected_paths)

    return BugFixLifecyclePaths(
        entry_root=entry_root,
        protected_root=protected_root,
        **entry_paths,
        **protected_paths,
    )


def validate_owned_lifecycle_roots(
    roots: tuple[OwnedLifecycleRoot, ...],
    paths: BugFixLifecyclePaths,
    expected_ownership_token: str,
) -> tuple[OwnedLifecycleRoot, ...]:
    validated_paths = validate_lifecycle_paths(paths)
    validated: list[OwnedLifecycleRoot] = []
    for index, owned_root in enumerate(roots):
        root_name = f"compiler_helper_roots[{index}]"
        root = absolute_path(owned_root.path)
        if root == Path(root.anchor):
            raise ValueError(f"{root_name} cannot be a filesystem root")
        require_disjoint(root, validated_paths.entry_root, root_name, "entry_root")
        require_disjoint(root, validated_paths.protected_root, root_name, "protected_root")
        reject_reparse_components(root, root)
        if not root.is_dir():
            raise ValueError(f"{root_name} must be an existing directory: {root}")
        if owned_root.ownership_token != expected_ownership_token:
            raise ValueError(f"{root_name} ownership token does not match the lifecycle invocation")
        marker = owned_root.marker_path
        reject_reparse_components(marker, root)
        if not marker.is_file() or marker.is_symlink():
            raise ValueError(f"{root_name} ownership marker is missing: {marker}")
        if marker.read_text(encoding="utf-8").strip() != expected_ownership_token:
            raise ValueError(f"{root_name} ownership marker does not match the lifecycle invocation")
        validated.append(OwnedLifecycleRoot(root, expected_ownership_token))

    for (first_index, first), (second_index, second) in combinations(enumerate(validated), 2):
        require_disjoint(
            first.path,
            second.path,
            f"compiler_helper_roots[{first_index}]",
            f"compiler_helper_roots[{second_index}]",
        )
    return tuple(validated)


def validate_provisioned_lifecycle_resources(
    resources: ProvisionedLifecycleResources,
) -> ProvisionedLifecycleResources:
    paths = validate_lifecycle_paths(resources.paths)
    benchmark_root = _require_directory_without_reparse(resources.benchmark_root, "benchmark_root")
    staged_worker = require_strict_descendant(
        resources.staged_worker_path,
        paths.agent_tools,
        "staged_worker_path",
        "agent_tools",
    )
    if not staged_worker.is_file() or staged_worker.is_symlink():
        raise ValueError(f"staged_worker_path must be an existing regular file: {staged_worker}")

    python_base_prefix = _validate_read_execute_root(
        resources.python_base_prefix,
        "python_base_prefix",
        benchmark_root,
        paths,
    )
    base_python = require_strict_descendant(
        resources.base_python,
        python_base_prefix,
        "base_python",
        "python_base_prefix",
    )
    if not base_python.is_file() or base_python.is_symlink():
        raise ValueError(f"base_python must be an existing regular file: {base_python}")

    cleanup_tool_roots = tuple(
        _validate_read_execute_root(
            root,
            f"cleanup_tool_roots[{index}]",
            benchmark_root,
            paths,
        )
        for index, root in enumerate(resources.cleanup_tool_roots)
    )
    compiler_helper_roots = validate_owned_lifecycle_roots(
        resources.compiler_helper_roots,
        paths,
        resources.expected_container_invocation_id,
    )
    acl_paths = validate_cleanup_acl_paths(resources)

    return replace(
        resources,
        paths=paths,
        benchmark_root=benchmark_root,
        staged_worker_path=staged_worker,
        base_python=base_python,
        python_base_prefix=python_base_prefix,
        cleanup_tool_roots=cleanup_tool_roots,
        acl_paths=acl_paths,
        compiler_helper_roots=compiler_helper_roots,
    )


def validate_agent_plugin_root(resources: ProvisionedLifecycleResources) -> Path:
    root = resources.paths.agent_tools / "plugins"
    reject_reparse_components(root, resources.paths.agent_tools)
    require_disjoint(root, resources.benchmark_root, "agent plugin root", "benchmark root")
    if root not in resources.cleanup_tool_roots:
        raise ValueError("Agent plugin root must be included in the setup ACL tool roots")
    marker = root / ".bcbench-owned"
    reject_reparse_components(marker, root)
    if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != resources.expected_container_invocation_id:
        raise ValueError("Agent plugin root ownership marker does not match the setup invocation")
    return root


def validate_cleanup_acl_paths(
    resources: ProvisionedLifecycleResources,
) -> tuple[Path, ...]:
    paths = validate_lifecycle_paths(resources.paths)
    benchmark_root = _require_directory_without_reparse(resources.benchmark_root, "benchmark_root")
    staged_worker = require_strict_descendant(
        resources.staged_worker_path,
        paths.agent_tools,
        "staged_worker_path",
        "agent_tools",
    )
    python_base_prefix = _validate_read_execute_root(
        resources.python_base_prefix,
        "python_base_prefix",
        benchmark_root,
        paths,
    )
    base_python = require_strict_descendant(
        resources.base_python,
        python_base_prefix,
        "base_python",
        "python_base_prefix",
    )
    if not base_python.is_file() or base_python.is_symlink():
        raise ValueError(f"base_python must be an existing regular file: {base_python}")
    cleanup_tool_roots = tuple(
        _validate_read_execute_root(
            root,
            f"cleanup_tool_roots[{index}]",
            benchmark_root,
            paths,
            require_exists=False,
        )
        for index, root in enumerate(resources.cleanup_tool_roots)
    )
    expected_acl_paths = tuple(
        dict.fromkeys(
            (
                benchmark_root,
                paths.entry_root,
                paths.baseline_workspace,
                paths.mounted_staging,
                paths.evaluator_workspaces,
                paths.evidence,
                paths.protected_root,
                paths.agent_workspace,
                paths.agent_logs,
                paths.agent_tools,
                staged_worker,
                *cleanup_tool_roots,
                python_base_prefix,
                base_python,
            )
        )
    )
    acl_paths = tuple(_canonical_path(path) for path in resources.acl_paths)
    if acl_paths != expected_acl_paths:
        raise ValueError("ACL transaction paths do not exactly match setup-provisioned runtime and tool roots")
    return acl_paths


def _require_directory_without_reparse(path: Path, name: str) -> Path:
    canonical = _canonical_path(path)
    if not canonical.is_dir() or canonical.is_symlink():
        raise ValueError(f"{name} must be an existing directory: {canonical}")
    return canonical


def _validate_read_execute_root(
    root: Path,
    name: str,
    benchmark_root: Path,
    paths: BugFixLifecyclePaths,
    *,
    require_exists: bool = True,
) -> Path:
    canonical = _require_directory_without_reparse(root, name) if require_exists else _canonical_path(root)
    restricted_paths = (
        benchmark_root,
        paths.protected_root,
        paths.baseline_workspace,
        paths.mounted_staging,
        paths.evaluator_workspaces,
        paths.evidence,
    )
    for restricted_path in restricted_paths:
        if paths_overlap(canonical, restricted_path):
            raise ValueError(f"{name} must not overlap restricted benchmark or lifecycle paths")
    if paths_overlap(canonical, paths.entry_root):
        allowed_roots = (paths.agent_workspace, paths.agent_logs, paths.agent_tools)
        if not any(canonical.is_relative_to(allowed_root) for allowed_root in allowed_roots):
            raise ValueError(f"{name} must be within an allowed agent root when inside entry_root")
    return canonical
