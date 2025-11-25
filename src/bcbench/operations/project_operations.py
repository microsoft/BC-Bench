"""Project path categorization and management operations."""

from bcbench.config import get_config
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
    project_lower = project_path.lower()
    return any(f"/{identifier}" in project_lower or f"\\{identifier}" in project_lower for identifier in test_identifiers)


def categorize_projects(project_paths: list[str]) -> tuple[list[str], list[str]]:
    """Categorize project paths into test projects and application projects.

    Args:
        project_paths: List of project paths to categorize

    Returns:
        Tuple of (test_projects, app_projects)

    Raises:
        RuntimeError: If project categorization fails (no test or app projects found)
    """
    test_identifiers = _config.file_patterns.test_project_identifiers
    test_projects: list[str] = [project for project in project_paths if _is_test_project(project, test_identifiers)]
    app_projects: list[str] = [project for project in project_paths if project not in test_projects]

    if not test_projects or not app_projects:
        logger.error(f"Project categorization failed. Test projects: {test_projects}, App projects: {app_projects}")
        raise RuntimeError(f"Project categorization failed: test_projects={test_projects}, app_projects={app_projects}")

    return test_projects, app_projects
