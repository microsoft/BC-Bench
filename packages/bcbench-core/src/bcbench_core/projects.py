"""Project path categorization for AL repositories."""

import logging

logger = logging.getLogger(__name__)


def is_test_project(project_path: str, test_identifiers: tuple[str, ...] = ("test", "tests")) -> bool:
    r"""Check if a project path is a test project.

    A path is a test project when one of its components, after a path separator (/ or \),
    starts with a test identifier: 'src/test' and 'src/test1' match 'test', 'src/contest' does not.

    Args:
        project_path: The project path to check
        test_identifiers: Case-insensitive prefixes that mark a test project component

    Returns:
        True if a path component starts with a test identifier
    """
    project_lower = project_path.lower()
    return any(f"/{identifier}" in project_lower or f"\\{identifier}" in project_lower for identifier in test_identifiers)


def categorize_projects(project_paths: list[str], test_identifiers: tuple[str, ...] = ("test", "tests")) -> tuple[list[str], list[str]]:
    """Categorize project paths into test projects and application projects.

    Args:
        project_paths: List of project paths to categorize
        test_identifiers: Case-insensitive prefixes that mark a test project component

    Returns:
        Tuple of (test_projects, app_projects)

    Raises:
        RuntimeError: If project categorization fails (no test or app projects found)
    """
    test_projects: list[str] = [project for project in project_paths if is_test_project(project, test_identifiers)]
    app_projects: list[str] = [project for project in project_paths if project not in test_projects]

    if not test_projects or not app_projects:
        logger.error(f"Project categorization failed. Test projects: {test_projects}, App projects: {app_projects}")
        raise RuntimeError(f"Project categorization failed: test_projects={test_projects}, app_projects={app_projects}")

    return test_projects, app_projects
