"""Business Central specific operations for building, publishing, and testing."""

import subprocess
from pathlib import Path
from string import Template
from typing import Literal

from pydantic import TypeAdapter

from bcbench.config import get_config
from bcbench.dataset import DatasetEntry, TestEntry
from bcbench.exceptions import BuildError, BuildTimeoutExpired, TestExecutionError, TestExecutionTimeoutExpired
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()


def _escape_ps_string(value: str) -> str:
    """Escape single quotes for PowerShell strings.

    In PowerShell single-quoted strings, single quotes are escaped by doubling them.
    """
    return value.replace("'", "''")


# PowerShell script templates using Python's built-in string.Template
_BUILD_AND_PUBLISH_TEMPLATE = Template(
    """
Import-Module BcContainerHelper -Force -DisableNameChecking
Import-Module '$app_utils_path' -Force
$$ErrorActionPreference = 'Stop'

$$projectPath = '$project_path'
$$password = ConvertTo-SecureString '$password' -AsPlainText -Force
$$credential = New-Object System.Management.Automation.PSCredential('$username', $$password)

Update-AppProjectVersion -ProjectPath $$projectPath -Version $version
Invoke-AppBuildAndPublish -containerName '$container_name' -appProjectFolder $$projectPath -credential $$credential -skipVerification -useDevEndpoint
""".strip()
)

_TEST_EXECUTION_TEMPLATE = Template(
    """
Import-Module BcContainerHelper -Force -DisableNameChecking
Import-Module '$app_utils_path' -Force
$$ErrorActionPreference = 'Stop'

$$password = ConvertTo-SecureString '$password' -AsPlainText -Force
$$credential = New-Object System.Management.Automation.PSCredential('$username', $$password)

Write-Host "Running tests for codeunit $codeunit_id"
Invoke-BCTest -containerName '$container_name' -credential $$credential -codeunitID $codeunit_id$function_param
""".strip()
)

_DATASET_TESTS_TEMPLATE = Template(
    """
Import-Module BcContainerHelper -Force -DisableNameChecking
Import-Module '$app_utils_path' -Force
$$ErrorActionPreference = 'Stop'

$$password = ConvertTo-SecureString '$password' -AsPlainText -Force
$$credential = New-Object System.Management.Automation.PSCredential('$username', $$password)

$$testEntries = '$test_entries_json' | ConvertFrom-Json

Invoke-DatasetTests -containerName '$container_name' -credential $$credential -testEntries $$testEntries -expectation '$expectation'
""".strip()
)


def build_ps_app_build_and_publish(container_name: str, username: str, password: str, project_path: Path, version: str) -> str:
    app_utils_path = _config.paths.ps_script_path / "AppUtils.psm1"

    return _BUILD_AND_PUBLISH_TEMPLATE.substitute(
        app_utils_path=_escape_ps_string(str(app_utils_path)),
        container_name=_escape_ps_string(container_name),
        username=_escape_ps_string(username),
        password=_escape_ps_string(password),
        project_path=_escape_ps_string(str(project_path)),
        version=version,
    )


def build_ps_test_script(container_name: str, username: str, password: str, codeunit_id: int, function_names: list[str] | None = None) -> str:
    app_utils_path = _config.paths.ps_script_path / "AppUtils.psm1"

    # Build function parameter if needed
    if function_names:
        escaped_names = [f"'{_escape_ps_string(fn)}'" for fn in function_names]
        function_param = f" -functionNames @({', '.join(escaped_names)})"
    else:
        function_param = ""

    return _TEST_EXECUTION_TEMPLATE.substitute(
        app_utils_path=_escape_ps_string(str(app_utils_path)),
        container_name=_escape_ps_string(container_name),
        username=_escape_ps_string(username),
        password=_escape_ps_string(password),
        codeunit_id=codeunit_id,
        function_param=function_param,
    )


def build_ps_dataset_tests_script(container_name: str, username: str, password: str, test_entries_json: str, expectation: Literal["Pass", "Fail"]) -> str:
    app_utils_path = _config.paths.ps_script_path / "AppUtils.psm1"

    return _DATASET_TESTS_TEMPLATE.substitute(
        app_utils_path=_escape_ps_string(str(app_utils_path)),
        container_name=_escape_ps_string(container_name),
        username=_escape_ps_string(username),
        password=_escape_ps_string(password),
        test_entries_json=_escape_ps_string(test_entries_json),
        expectation=_escape_ps_string(expectation),
    )


def build_and_publish_projects(repo_path: Path, project_paths: list[str], container_name: str, username: str, password: str, version: str) -> None:
    """Build and publish all projects."""
    logger.info(f"Building and publishing {len(project_paths)} projects")

    for project_path in project_paths:
        full_project_path = repo_path / project_path
        logger.info(f"Building project: {full_project_path}")

        ps_script = build_ps_app_build_and_publish(
            container_name=container_name,
            username=username,
            password=password,
            project_path=full_project_path,
            version=version,
        )

        # Extend timeout for build and publish, especially for BaseApp
        timeout = _config.timeout.build_baseapp if ("BaseApp" in project_path) else _config.timeout.build_app

        try:
            subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                cwd=repo_path,
                capture_output=True,
                check=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as e:
            logger.debug(f"Build failed for {project_path}")
            logger.debug(f"Full command output: {e.stdout}")
            raise BuildError(project_path, e.stdout) from None
        except subprocess.TimeoutExpired:
            logger.error(f"Build timed out for {project_path} after {timeout} seconds")
            raise BuildTimeoutExpired(project_path, timeout) from None

        logger.info(f"Successfully built and published: {project_path}")

    logger.info("All projects built and published")


def run_tests(entry: DatasetEntry, container_name: str, username: str, password: str) -> None:
    if entry.fail_to_pass:
        logger.info(f"Running {len(entry.fail_to_pass)} fail-to-pass tests")
        run_test_suite(entry.fail_to_pass, "Pass", container_name, username, password)

    if entry.pass_to_pass:
        logger.info(f"Running {len(entry.pass_to_pass)} pass-to-pass tests")
        run_test_suite(entry.pass_to_pass, "Pass", container_name, username, password)

    logger.info("All tests completed")


def run_test_suite(test_entries: list[TestEntry], expectation: Literal["Pass", "Fail"], container_name: str, username: str, password: str) -> None:
    """Run a suite of tests."""
    test_entries_json: str = TypeAdapter(list[TestEntry]).dump_json(test_entries).decode()

    ps_script = build_ps_dataset_tests_script(
        container_name=container_name,
        username=username,
        password=password,
        test_entries_json=test_entries_json,
        expectation=expectation,
    )

    try:
        logger.info(f"Running test suite with expectation: {expectation}")
        logger.info(f"Tests to run: {test_entries_json}")
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            check=True,
            text=True,
            timeout=_config.timeout.test_execution,
        )
        logger.info(f"Test suite completed with expectation met: {expectation}")
        if result.stdout:
            logger.debug(f"Test output:\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.debug(f"Test result did not meet expectation (expected: {expectation})")
        logger.debug(f"Full test output: {e.stdout}")
        raise TestExecutionError(expectation, e.stderr, e.stdout) from None
    except subprocess.TimeoutExpired:
        logger.error(f"Test execution timed out after {_config.timeout.test_execution} seconds")
        raise TestExecutionTimeoutExpired(test_entries_json, _config.timeout.test_execution) from None
