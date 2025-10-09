"""Business Central specific operations for building, publishing, and testing."""

import subprocess
from pathlib import Path
from typing import Optional

from bcbench.core.logger import get_logger
from bcbench.core.utils import PS_SCRIPT_PATH

logger = get_logger(__name__)


def _build_ps_script_header(app_utils_path: Path) -> str:
    """Build common PowerShell script header with module imports."""
    return f"""
Import-Module BcContainerHelper -Force -DisableNameChecking
Import-Module '{app_utils_path}' -Force
$ErrorActionPreference = 'Stop'
"""


def _build_ps_credential_setup(username: str, password: str) -> str:
    """Build PowerShell credential setup commands."""
    return f"""
$password = ConvertTo-SecureString '{password}' -AsPlainText -Force
$credential = New-Object System.Management.Automation.PSCredential('{username}', $password)
"""


def build_ps_app_build_and_publish(container_name: str, username: str, password: str, project_path: str, version: str) -> str:
    """Build complete PowerShell script for app build and publish."""
    app_utils_path = PS_SCRIPT_PATH / "AppUtils.psm1"

    return (
        _build_ps_script_header(app_utils_path)
        + f"\n$projectPath = '{project_path}'"
        + _build_ps_credential_setup(username, password)
        + f"\nUpdate-AppProjectVersion -ProjectPath $projectPath -Version {version}"
        + f"\nInvoke-AppBuildAndPublish -containerName '{container_name}' -appProjectFolder $projectPath -credential $credential -skipVerification -useDevEndpoint\n"
    )


def build_ps_test_script(
    container_name: str,
    username: str,
    password: str,
    codeunit_id: int,
    function_names: Optional[list[str]] = None,
) -> str:
    """Build complete PowerShell script for running tests."""
    app_utils_path = PS_SCRIPT_PATH / "AppUtils.psm1"

    if function_names:
        function_array = ", ".join([f"'{fn}'" for fn in function_names])
        function_param = f"-functionNames @({function_array})"
    else:
        function_param = ""

    return (
        _build_ps_script_header(app_utils_path)
        + _build_ps_credential_setup(username, password)
        + f'\nWrite-Host "Running tests for codeunit {codeunit_id}"\n'
        + f"Invoke-BCTest -containerName '{container_name}' -credential $credential -codeunitID {codeunit_id} {function_param}\n"
    )


def build_ps_dataset_tests_script(
    container_name: str,
    username: str,
    password: str,
    test_entries_json: str,
    expectation: str,
) -> str:
    """Build complete PowerShell script for running dataset tests."""
    app_utils_path = PS_SCRIPT_PATH / "AppUtils.psm1"

    return (
        _build_ps_script_header(app_utils_path)
        + _build_ps_credential_setup(username, password)
        + f"\n$testEntries = '{test_entries_json}' | ConvertFrom-Json\n"
        + f"\nInvoke-DatasetTests -containerName '{container_name}' -credential $credential -testEntries $testEntries -expectation '{expectation}'\n"
    )


def build_and_publish_projects(
    repo_path: Path,
    project_paths: list,
    container_name: str,
    username: str,
    password: str,
    version: str,
) -> None:
    """Build and publish all projects."""
    logger.info(f"Building and publishing {len(project_paths)} projects")

    for project_path in project_paths:
        full_project_path = repo_path / project_path
        logger.info(f"Building project: {full_project_path}")

        ps_script = build_ps_app_build_and_publish(
            container_name=container_name,
            username=username,
            password=password,
            project_path=str(full_project_path),
            version=version,
        )

        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error(f"Build failed for {project_path}: {result.stderr}")
            logger.error(f"Full command output: {result.stdout}")
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

    if entry.fail_to_pass:
        logger.info(f"Running {len(entry.fail_to_pass)} fail-to-pass tests")
        _run_test_suite(entry.fail_to_pass, "Pass", container_name, username, password)

    if entry.pass_to_pass:
        logger.info(f"Running {len(entry.pass_to_pass)} pass-to-pass tests")
        _run_test_suite(entry.pass_to_pass, "Pass", container_name, username, password)

    logger.info("All tests completed")


def _run_test_suite(
    test_entries: list,
    expectation: str,
    container_name: str,
    username: str,
    password: str,
) -> None:
    """Run a suite of tests."""
    test_entries_json = str(test_entries).replace("'", '"')

    ps_script = build_ps_dataset_tests_script(
        container_name=container_name,
        username=username,
        password=password,
        test_entries_json=test_entries_json,
        expectation=expectation,
    )

    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error(f"Tests failed: {result.stderr}")
        raise RuntimeError(f"Tests failed with expectation: {expectation}")
