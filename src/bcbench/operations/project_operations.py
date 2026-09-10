"""Project path categorization and management operations."""

from collections.abc import Iterable
from pathlib import Path

from bcbench.config import get_config
from bcbench.exceptions import ProjectDiscoveryError
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()


def _is_test_project(project_path: str, test_identifiers: tuple[str, ...]) -> bool:
    r"""Check if a project path is a test project based on configured identifiers.

    The function checks if any test identifier appears as a complete path component
    by looking for the identifier preceded by a path separator (/ or \).
    This ensures that 'src/contest' does not match 'test', but 'src/test' does.

    Args:
        project_path: The project path to check
        test_identifiers: Tuple of test identifier strings (e.g., 'test', 'tests')

    Returns:
        True if the project path contains a test identifier as a path component
    """
    project_casefolded = project_path.casefold()
    return any(f"/{identifier.casefold()}" in project_casefolded or f"\\{identifier.casefold()}" in project_casefolded for identifier in test_identifiers)


def is_test_project(project_path: str) -> bool:
    """Check if a project path is a test project."""
    return _is_test_project(project_path, _config.file_patterns.test_project_identifiers)


def _canonical_project_path(project_path: str) -> str:
    """Normalize a project path for comparison."""
    return project_path.replace("\\", "/").rstrip("/").casefold()


def _project_path_representative_key(project_path: str) -> tuple[bool, str, str]:
    canonical_path = _canonical_project_path(project_path)
    return project_path != canonical_path, project_path.casefold(), project_path


def find_project_path(repo_path: Path, file_path: str) -> str:
    """Find the nearest AL project that owns a changed file."""
    resolved_repo_path = repo_path.resolve()
    resolved_file_path = (resolved_repo_path / Path(file_path.replace("\\", "/"))).resolve()

    if not resolved_file_path.is_relative_to(resolved_repo_path):
        raise ProjectDiscoveryError(f"Changed path is outside repository: {file_path}")

    current_path = resolved_file_path.parent
    while current_path.is_relative_to(resolved_repo_path):
        if (current_path / "app.json").is_file():
            return str(current_path.relative_to(resolved_repo_path))
        if current_path == resolved_repo_path:
            break
        current_path = current_path.parent

    raise ProjectDiscoveryError(f"No owning app.json found for {file_path}")


def order_project_paths(preferred_paths: Iterable[str], discovered_paths: Iterable[str]) -> list[str]:
    """Order discovered projects by preferred order, then canonical path."""
    discovered_by_canonical_path: dict[str, str] = {}
    for discovered_path in discovered_paths:
        canonical_path = _canonical_project_path(discovered_path)
        representative = discovered_by_canonical_path.get(canonical_path)
        if representative is None or _project_path_representative_key(discovered_path) < _project_path_representative_key(representative):
            discovered_by_canonical_path[canonical_path] = discovered_path

    ordered_paths: list[str] = []
    for preferred_path in preferred_paths:
        canonical_path = _canonical_project_path(preferred_path)
        discovered_path = discovered_by_canonical_path.pop(canonical_path, None)
        if discovered_path is not None:
            ordered_paths.append(discovered_path)

    ordered_paths.extend(discovered_by_canonical_path[canonical_path] for canonical_path in sorted(discovered_by_canonical_path))
    return ordered_paths


def categorize_projects(project_paths: list[str]) -> tuple[list[str], list[str]]:
    """Categorize project paths into test projects and application projects.

    Args:
        project_paths: List of project paths to categorize

    Returns:
        Tuple of (test_projects, app_projects)

    Raises:
        RuntimeError: If project categorization fails (no test or app projects found)
    """
    test_projects: list[str] = [project for project in project_paths if is_test_project(project)]
    app_projects: list[str] = [project for project in project_paths if project not in test_projects]

    if not test_projects or not app_projects:
        logger.error(f"Project categorization failed. Test projects: {test_projects}, App projects: {app_projects}")
        raise RuntimeError(f"Project categorization failed: test_projects={test_projects}, app_projects={app_projects}")

    return test_projects, app_projects
