import os
import stat
from itertools import combinations
from pathlib import Path

from bcbench.evaluate.bugfix_lifecycle.models import BugFixLifecyclePaths

ENTRY_MANAGED_PATH_NAMES = (
    "baseline_workspace",
    "agent_workspace",
    "agent_logs",
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
