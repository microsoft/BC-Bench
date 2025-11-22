"""Project path categorization and management operations."""

from bcbench.config import get_config
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()


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
    test_projects: list[str] = [project for project in project_paths if any(f"/{identifier}" in project.lower() or f"\\{identifier}" in project.lower() for identifier in test_identifiers)]
    app_projects: list[str] = [project for project in project_paths if project not in test_projects]

    if not test_projects or not app_projects:
        logger.error(f"Project categorization failed. Test projects: {test_projects}, App projects: {app_projects}")
        raise RuntimeError(f"Project categorization failed: test_projects={test_projects}, app_projects={app_projects}")

    return test_projects, app_projects
