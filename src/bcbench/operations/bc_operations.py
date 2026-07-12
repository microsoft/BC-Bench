"""Business Central specific operations for building, publishing, and testing."""

import shutil
import subprocess
from pathlib import Path
from string import Template
from typing import Literal

from pydantic import TypeAdapter

from bcbench.config import get_config
from bcbench.dataset import TestEntry
from bcbench.dataset.dataset_entry import _BugFixTestGenBase
from bcbench.exceptions import BuildError, BuildTimeoutExpired, TestExecutionError, TestExecutionTimeoutExpired
from bcbench.logger import get_logger
from bcbench.types import ContainerConfig

logger = get_logger(__name__)
_config = get_config()


def resolve_artifact_version_root(version: str) -> Path | None:
    """Return the newest BCContainerHelper artifact folder matching a major.minor version.

    The dataset's ``environment_setup_version`` is major.minor (e.g. "27.2"); BCContainerHelper
    expands that to a full ``<major>.<minor>.<build>.<revision>`` folder under
    ``<bc_artifacts_cache>/sandbox/``. We glob, lexically sort, and pick the newest -- BC's
    full-version fields are constant-width in practice, so a lexical sort matches a numeric one.

    Returns None when no matching artifact has been downloaded yet.
    """
    version_roots = sorted((_config.paths.bc_artifacts_cache / "sandbox").glob(f"{version}.*"))
    return version_roots[-1] if version_roots else None


def copy_symbol_apps(project_dir: Path, version: str) -> None:
    """Copy all *.app symbol files from the BC artifact cache into the project's .alpackages."""
    version_root = resolve_artifact_version_root(version)
    if version_root is None:
        raise FileNotFoundError(f"No BC artifact for version {version} under {_config.paths.bc_artifacts_cache / 'sandbox'}. Run scripts/Download-BCSymbols.ps1 to populate the cache.")

    app_files = list(version_root.rglob("*.app"))
    if not app_files:
        raise FileNotFoundError(f"No *.app files found under {version_root}.")

    alpackages_dir = project_dir / _config.file_patterns.alpackages_dirname
    alpackages_dir.mkdir(parents=True, exist_ok=True)
    for app_file in app_files:
        shutil.copy2(app_file, alpackages_dir / app_file.name)
    logger.info(f"Copied {len(app_files)} *.app files from {version_root} to {alpackages_dir}")


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


def build_and_publish_projects(repo_path: Path, project_paths: list[str], container: ContainerConfig, version: str) -> None:
    """Build and publish all projects."""
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
            logger.exception(f"Build timed out for {project_path} after {timeout} seconds")
            raise BuildTimeoutExpired(project_path, timeout) from None

        logger.info(f"Successfully built and published: {project_path}")

    logger.info("All projects built and published")


def run_tests(entry: _BugFixTestGenBase, container: ContainerConfig) -> None:
    if entry.fail_to_pass:
        logger.info(f"Running {len(entry.fail_to_pass)} fail-to-pass tests")
        run_test_suite(entry.fail_to_pass, "Pass", container)

    if entry.pass_to_pass:
        logger.info(f"Running {len(entry.pass_to_pass)} pass-to-pass tests")
        run_test_suite(entry.pass_to_pass, "Pass", container)

    logger.info("All tests completed")


def run_test_suite(test_entries: list[TestEntry], expectation: Literal["Pass", "Fail"], container: ContainerConfig) -> None:
    """Run a suite of tests."""
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
        logger.exception(f"Test execution timed out after {_config.timeout.test_execution} seconds")
        raise TestExecutionTimeoutExpired(test_entries_json, _config.timeout.test_execution) from None


# --- data-query category: compile + run an AL query and capture its rows via a wrapped API query ---

# API metadata injected into a generated/gold query so it is exposed over OData and can be fetched.
_QUERY_API_PUBLISHER = "bcbench"
_QUERY_API_GROUP = "eval"
_QUERY_API_VERSION = "v1.0"
_QUERY_API_ENTITY_SET = "bcbenchResults"

_QUERY_API_PROPERTIES = (
    "QueryType = API;\n"
    f"    APIPublisher = '{_QUERY_API_PUBLISHER}';\n"
    f"    APIGroup = '{_QUERY_API_GROUP}';\n"
    f"    APIVersion = '{_QUERY_API_VERSION}';\n"
    "    EntityName = 'bcbenchResult';\n"
    f"    EntitySetName = '{_QUERY_API_ENTITY_SET}';\n"
    "    Extensible = false;"
)


def wrap_query_as_api(query_text: str, object_id: int) -> str:
    """Turn a plain AL query object into an API query the harness can fetch over OData.

    Reassigns the object id (so generated and gold apps don't collide), drops any existing
    ``QueryType`` line, and injects the API properties right after the object's opening brace.
    Pure string transform so it can be unit-tested without a container.
    """
    import re

    text = re.sub(r"(\bquery\s+)\d+", rf"\g<1>{object_id}", query_text, count=1)
    text = re.sub(r"\n\s*QueryType\s*=\s*\w+\s*;", "", text, count=1)

    brace_index = text.index("{")
    return f"{text[: brace_index + 1]}\n    {_QUERY_API_PROPERTIES}\n{text[brace_index + 1 :]}"


_QUERY_RUN_TEMPLATE = Template(
    """
Import-Module BcContainerHelper -Force -DisableNameChecking
$$ErrorActionPreference = 'Stop'

$$password = ConvertTo-SecureString '$password' -AsPlainText -Force
$$credential = New-Object System.Management.Automation.PSCredential('$username', $$password)

$$appFile = Compile-AppInBcContainer -containerName '$container_name' -credential $$credential -appProjectFolder '$app_dir' -appOutputFolder '$app_dir\\out' -UpdateSymbols
Publish-BcContainerApp -containerName '$container_name' -appFile $$appFile -skipVerification -sync -install -credential $$credential

$$base = "http://$container_name/BC/api"
$$companyId = (Invoke-RestMethod -Uri "$$base/v2.0/companies" -Credential $$credential).value[0].id
$$data = Invoke-RestMethod -Uri "$$base/$publisher/$group/$version/companies($$companyId)/$entity_set" -Credential $$credential
$$data.value | ConvertTo-Json -Depth 10 -Compress | Out-File -FilePath '$result_file' -Encoding utf8
""".strip()
)


def execute_al_query(query_text: str, container: ContainerConfig, version: str, work_root: Path, suffix: str) -> list[dict]:
    """Compile + publish an AL query (wrapped as an API query) to the container and return its rows.

    Builds a throwaway app under ``work_root/.bcbench-query-<suffix>``, compiles + publishes it,
    then reads the query's OData endpoint. Raises :class:`BuildError` if the query does not
    compile or publish.

    NOTE: the container-side steps (compile/publish/OData fetch) require a running BC container
    and have not been validated locally; the wrapping and comparison logic are unit-tested.
    """
    import json
    from uuid import uuid4

    object_id = 50100 if suffix == "generated" else 50101
    app_dir = work_root / f".bcbench-query-{suffix}"
    if app_dir.exists():
        shutil.rmtree(app_dir, onexc=lambda func, path, _: (Path(path).chmod(0o666), func(path)))
    app_dir.mkdir(parents=True, exist_ok=True)

    app_manifest = {
        "id": str(uuid4()),
        "name": f"BC-Bench Query {suffix}",
        "publisher": "BC-Bench",
        "version": "1.0.0.0",
        "application": f"{version.split('.')[0]}.0.0.0",
        "platform": f"{version.split('.')[0]}.0.0.0",
        "idRanges": [{"from": object_id, "to": object_id}],
        "runtime": "13.0",
        "target": "OnPrem",
    }
    (app_dir / "app.json").write_text(json.dumps(app_manifest, indent=2), encoding="utf-8")
    (app_dir / "query.al").write_text(wrap_query_as_api(query_text, object_id), encoding="utf-8")
    # Symbols come from the container via Compile-AppInBcContainer -UpdateSymbols (below); no need
    # to pre-populate .alpackages from the artifact cache.

    result_file = app_dir / "result.json"
    ps_script = _QUERY_RUN_TEMPLATE.substitute(
        container_name=_escape_ps_string(container.name),
        username=_escape_ps_string(container.username),
        password=_escape_ps_string(container.password),
        app_dir=_escape_ps_string(str(app_dir)),
        publisher=_QUERY_API_PUBLISHER,
        group=_QUERY_API_GROUP,
        version=_QUERY_API_VERSION,
        entity_set=_QUERY_API_ENTITY_SET,
        result_file=_escape_ps_string(str(result_file)),
    )

    try:
        subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            cwd=work_root,
            capture_output=True,
            check=True,
            text=True,
            timeout=_config.timeout.build_app,
        )
    except subprocess.CalledProcessError as e:
        logger.debug(f"Query compile/publish/fetch failed ({suffix}): {e.stdout}\n{e.stderr}")
        raise BuildError(f"query-{suffix}", (e.stdout or "") + (e.stderr or "")) from None
    except subprocess.TimeoutExpired:
        raise BuildTimeoutExpired(f"query-{suffix}", _config.timeout.build_app) from None

    rows = json.loads(result_file.read_text(encoding="utf-8-sig") or "[]")
    return rows if isinstance(rows, list) else [rows]

