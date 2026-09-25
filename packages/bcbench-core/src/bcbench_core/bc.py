"""Business Central specific operations for building, publishing, and testing."""

import logging
import subprocess
from pathlib import Path
from string import Template
from typing import Final, Literal

from pydantic import TypeAdapter

from bcbench_core.container import ContainerConfig
from bcbench_core.dataset import TestEntry
from bcbench_core.exceptions import BuildError, BuildTimeoutExpired, TestExecutionError, TestExecutionTimeoutExpired

logger = logging.getLogger(__name__)

# PowerShell modules shipped with this package; the generated scripts import them
POWERSHELL_DIR: Final = Path(__file__).with_name("powershell")
APP_UTILS_MODULE: Final = POWERSHELL_DIR / "AppUtils.psm1"
BCBENCH_UTILS_MODULE: Final = POWERSHELL_DIR / "BCBenchUtils.psm1"


def escape_ps_string(value: str) -> str:
    """Escape single quotes for PowerShell strings.

    In PowerShell single-quoted strings, single quotes are escaped by doubling them.
    """
    return value.replace("'", "''")


# PowerShell script templates using Python's built-in string.Template
_BUILD_AND_PUBLISH_TEMPLATE = Template(
    """
Import-Module BcContainerHelper -Force -DisableNameChecking
Import-Module '$bcbench_utils_path' -Force
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
    return _BUILD_AND_PUBLISH_TEMPLATE.substitute(
        bcbench_utils_path=escape_ps_string(str(BCBENCH_UTILS_MODULE)),
        app_utils_path=escape_ps_string(str(APP_UTILS_MODULE)),
        container_name=escape_ps_string(container_name),
        username=escape_ps_string(username),
        password=escape_ps_string(password),
        project_path=escape_ps_string(str(project_path)),
        version=version,
    )


def build_ps_test_script(container_name: str, username: str, password: str, codeunit_id: int, function_names: list[str] | None = None) -> str:
    # Build function parameter if needed
    if bool(function_names):
        escaped_names = [f"'{escape_ps_string(fn)}'" for fn in function_names]
        function_param = f" -functionNames @({', '.join(escaped_names)})"
    else:
        function_param = ""

    return _TEST_EXECUTION_TEMPLATE.substitute(
        app_utils_path=escape_ps_string(str(APP_UTILS_MODULE)),
        container_name=escape_ps_string(container_name),
        username=escape_ps_string(username),
        password=escape_ps_string(password),
        codeunit_id=codeunit_id,
        function_param=function_param,
    )


def build_ps_dataset_tests_script(container_name: str, username: str, password: str, test_entries_json: str, expectation: Literal["Pass", "Fail"]) -> str:
    return _DATASET_TESTS_TEMPLATE.substitute(
        app_utils_path=escape_ps_string(str(APP_UTILS_MODULE)),
        container_name=escape_ps_string(container_name),
        username=escape_ps_string(username),
        password=escape_ps_string(password),
        test_entries_json=escape_ps_string(test_entries_json),
        expectation=escape_ps_string(expectation),
    )


def build_and_publish_projects(repo_path: Path, project_paths: list[str], container: ContainerConfig, version: str, timeout: int = 5 * 60, baseapp_timeout: int = 30 * 60) -> None:
    """Build and publish all projects; Base Application compiles far slower than other apps, so it gets `baseapp_timeout`."""
    logger.info(f"Building and publishing {len(project_paths)} projects")

    for project_path in project_paths:
        full_project_path = repo_path / project_path
        logger.info(f"Building project: {full_project_path}")

        ps_script = build_ps_app_build_and_publish(
            container_name=container.name,
            username=container.username,
            password=container.password,
            project_path=full_project_path,
            version=version,
        )

        project_timeout = baseapp_timeout if ("BaseApp" in project_path) else timeout

        try:
            subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                cwd=repo_path,
                capture_output=True,
                check=True,
                text=True,
                timeout=project_timeout,
            )
        except subprocess.CalledProcessError as e:
            logger.debug(f"Build failed for {project_path}")
            logger.debug(f"Full command output: {e.stdout}")
            raise BuildError(project_path, e.stdout) from None
        except subprocess.TimeoutExpired:
            logger.exception(f"Build timed out for {project_path} after {project_timeout} seconds")
            raise BuildTimeoutExpired(project_path, project_timeout) from None

        logger.info(f"Successfully built and published: {project_path}")

    logger.info("All projects built and published")


def run_test_suite(test_entries: list[TestEntry], expectation: Literal["Pass", "Fail"], container: ContainerConfig, timeout: int = 3 * 60) -> None:
    """Run a suite of tests; "Pass" requires every test to pass, "Fail" at least one failure."""
    test_entries_json: str = TypeAdapter(list[TestEntry]).dump_json(test_entries).decode()

    ps_script = build_ps_dataset_tests_script(
        container_name=container.name,
        username=container.username,
        password=container.password,
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
            timeout=timeout,
        )
        logger.info(f"Test suite completed with expectation met: {expectation}")
        if result.stdout:
            logger.debug(f"Test output:\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        logger.debug(f"Test result did not meet expectation (expected: {expectation})")
        logger.debug(f"Full test output: {e.stdout}")
        raise TestExecutionError(expectation, e.stderr, e.stdout) from None
    except subprocess.TimeoutExpired:
        logger.exception(f"Test execution timed out after {timeout} seconds")
        raise TestExecutionTimeoutExpired(test_entries_json, timeout) from None
