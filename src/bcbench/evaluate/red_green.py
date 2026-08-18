from pathlib import Path

from bcbench.dataset import TestEntry
from bcbench.dataset.dataset_entry import _BugFixTestGenBase
from bcbench.logger import get_logger
from bcbench.operations import apply_patch, build_and_publish_projects
from bcbench.operations.bc_operations import run_test_suite
from bcbench.types import ContainerConfig

logger = get_logger(__name__)

__all__ = ["run_red_green_check"]


def run_red_green_check(
    *,
    repo_path: Path,
    entry: _BugFixTestGenBase,
    container: ContainerConfig,
    generated_tests: list[TestEntry],
    initial_build_projects: list[str],
    app_projects: list[str],
) -> None:
    """Assert generated tests fail on unfixed code and pass once the gold patch is applied.

    Args:
        repo_path: Repository under evaluation, already reduced to base code plus the generated tests.
        entry: Dataset entry supplying the gold ``patch`` and the environment version.
        container: BC container to build, publish and run against.
        generated_tests: Tests extracted from the agent's patch.
        initial_build_projects: Projects to build before the red run. Pass every project when the
            agent may have published its own fix into the container, so the base app is restored.
        app_projects: Projects to rebuild after the gold patch is applied.

    Raises:
        BuildError: If any build or publish fails.
        TestExecutionError: If the red or green expectation is not met.
    """
    build_and_publish_projects(repo_path, initial_build_projects, container, entry.environment_setup_version)
    run_test_suite(generated_tests, "Fail", container)

    apply_patch(repo_path, entry.patch, f"{entry.instance_id} gold patch")

    build_and_publish_projects(repo_path, app_projects, container, entry.environment_setup_version)
    run_test_suite(generated_tests, "Pass", container)
