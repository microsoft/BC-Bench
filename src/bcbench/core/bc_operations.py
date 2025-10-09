"""Business Central specific operations for building, publishing, and testing."""

import subprocess
from pathlib import Path

from bcbench.core.logger import get_logger
from bcbench.core.utils import PS_SCRIPT_PATH

logger = get_logger(__name__)


def build_and_publish_projects(
    repo_path: Path,
    project_paths: list,
    container_name: str,
    username: str,
    password: str,
) -> None:
    """Build and publish all projects."""
    logger.info(f"Building and publishing {len(project_paths)} projects")

    app_utils_path = PS_SCRIPT_PATH / "AppUtils.psm1"

    for project_path in project_paths:
        logger.info(f"Building project: {project_path}")
        full_project_path = repo_path / project_path

        ps_script = f"""
Import-Module BcContainerHelper -Force -DisableNameChecking
Import-Module '{app_utils_path}' -Force
$ErrorActionPreference = 'Stop'

$projectPath = '{full_project_path}'
$password = ConvertTo-SecureString '{password}' -AsPlainText -Force
$credential = New-Object System.Management.Automation.PSCredential('{username}', $password)

Invoke-AppBuildAndPublish -containerName '{container_name}' -appProjectFolder $projectPath -credential $credential -skipVerification -useDevEndpoint
"""

        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error(f"Build failed for {project_path}: {result.stderr}")
            raise RuntimeError(f"Build failed for {project_path}")

        logger.info(f"Successfully built and published: {project_path}")

    logger.info("All projects built and published")


def run_tests(
    entry,
    container_name: str,
    username: str,
    password: str,
) -> None:
    """Run fail-to-pass and pass-to-pass tests."""
    logger.info("Running tests")

    app_utils_path = PS_SCRIPT_PATH / "AppUtils.psm1"

    if entry.fail_to_pass:
        logger.info(f"Running {len(entry.fail_to_pass)} fail-to-pass tests")
        _run_test_suite(entry.fail_to_pass, "Pass", container_name, username, password, app_utils_path)

    if entry.pass_to_pass:
        logger.info(f"Running {len(entry.pass_to_pass)} pass-to-pass tests")
        _run_test_suite(entry.pass_to_pass, "Pass", container_name, username, password, app_utils_path)

    logger.info("All tests completed")


def _run_test_suite(
    test_entries: list,
    expectation: str,
    container_name: str,
    username: str,
    password: str,
    app_utils_path: Path,
) -> None:
    """Run a suite of tests."""
    test_entries_json = str(test_entries).replace("'", '"')

    ps_script = f"""
Import-Module BcContainerHelper -Force -DisableNameChecking
Import-Module '{app_utils_path}' -Force
$ErrorActionPreference = 'Stop'

$password = ConvertTo-SecureString '{password}' -AsPlainText -Force
$credential = New-Object System.Management.Automation.PSCredential('{username}', $password)

$testEntries = '{test_entries_json}' | ConvertFrom-Json

Invoke-DatasetTests -containerName '{container_name}' -credential $credential -testEntries $testEntries -expectation '{expectation}'
"""

    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error(f"Tests failed: {result.stderr}")
        raise RuntimeError(f"Tests failed with expectation: {expectation}")
