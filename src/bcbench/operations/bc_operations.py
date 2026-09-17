"""Business Central specific operations for building, publishing, and testing."""

import json
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from string import Template
from typing import Literal

from bcbench.config import get_config
from bcbench.dataset import TestEntry
from bcbench.dataset.dataset_entry import _BugFixTestGenBase
from bcbench.exceptions import (
    BuildError,
    BuildTimeoutExpired,
    TestExecutionError,
    TestExecutionFailureKind,
    TestExecutionTimeoutExpired,
    TestInfrastructureError,
)
from bcbench.logger import get_logger
from bcbench.operations.filesystem_operations import remove_tree
from bcbench.operations.setup_operations import bootstrap_app_json
from bcbench.operations.test_execution import TestExpectation, TestRunSummary, load_test_run_summary
from bcbench.types import ContainerConfig

logger = get_logger(__name__)
_config = get_config()


@dataclass(frozen=True)
class ProjectBuildEvidence:
    project_path: str
    command_path: Path
    stdout_path: Path
    stderr_path: Path
    diagnostics_path: Path
    package_path: Path
    package_hash: str


@dataclass(frozen=True)
class ProjectPublicationEvidence:
    projects: tuple[ProjectBuildEvidence, ...]

    @property
    def package_paths(self) -> tuple[Path, ...]:
        return tuple(project.package_path for project in self.projects)


@dataclass(frozen=True)
class TestSuiteEvidence:
    summary: TestRunSummary
    command_path: Path
    stdout_path: Path
    stderr_path: Path
    discovery_paths: tuple[Path, ...]
    junit_paths: tuple[Path, ...]


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_evidence(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _prepare_evidence_directory(path: Path) -> Path:
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"Evidence directory must be empty: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _redacted_command(script: str, password: str) -> str:
    escaped_password = _escape_ps_string(password)
    redacted_script = script.replace(f"'{escaped_password}'", "'***'")
    return (
        json.dumps(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", redacted_script],
            indent=2,
        )
        + "\n"
    )


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
$$evidenceRoot = '$evidence_directory'
$$evidenceDirectory = Join-Path $$evidenceRoot "bcbench-test-evidence-$$([System.Guid]::NewGuid())"
try {
    Invoke-BCTest -containerName '$container_name' -credential $$credential -codeunitID $codeunit_id$function_param -evidenceDirectory $$evidenceDirectory
}
finally {
    Remove-Item -Path $$evidenceDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
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

Invoke-DatasetTests -containerName '$container_name' -credential $$credential -testEntries $$testEntries -evidenceDirectory '$evidence_directory'
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


def build_ps_test_script(
    container_name: str,
    username: str,
    password: str,
    codeunit_id: int,
    function_names: list[str] | None = None,
    evidence_directory: Path | None = None,
) -> str:
    app_utils_path = _config.paths.ps_script_path / "AppUtils.psm1"
    evidence_root = evidence_directory or Path.cwd()

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
        evidence_directory=_escape_ps_string(str(evidence_root)),
    )


def build_ps_dataset_tests_script(container_name: str, username: str, password: str, test_entries_json: str, evidence_directory: Path) -> str:
    app_utils_path = _config.paths.ps_script_path / "AppUtils.psm1"

    return _DATASET_TESTS_TEMPLATE.substitute(
        app_utils_path=_escape_ps_string(str(app_utils_path)),
        container_name=_escape_ps_string(container_name),
        username=_escape_ps_string(username),
        password=_escape_ps_string(password),
        test_entries_json=_escape_ps_string(test_entries_json),
        evidence_directory=_escape_ps_string(str(evidence_directory)),
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


def build_and_publish_projects_with_evidence(
    repo_path: Path,
    project_paths: list[str],
    container: ContainerConfig,
    version: str,
    evidence_directory: Path,
) -> ProjectPublicationEvidence:
    evidence_root = _prepare_evidence_directory(evidence_directory)
    records: list[ProjectBuildEvidence] = []
    logger.info(f"Building and publishing {len(project_paths)} projects with evidence")

    for index, project_path in enumerate(project_paths):
        full_project_path = repo_path / project_path
        project_evidence = evidence_root / f"{index:03d}-{Path(project_path).name}"
        project_evidence.mkdir(parents=True)
        ps_script = build_ps_app_build_and_publish(
            container_name=container.name,
            username=container.username,
            password=container.password,
            project_path=full_project_path,
            version=version,
        )
        command_path = _write_evidence(
            project_evidence / "command.json",
            _redacted_command(ps_script, container.password),
        )
        stdout_path = project_evidence / "stdout.txt"
        stderr_path = project_evidence / "stderr.txt"
        diagnostics_path = project_evidence / "publication.json"
        timeout = _config.timeout.build_baseapp if "BaseApp" in project_path else _config.timeout.build_app

        try:
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                cwd=repo_path,
                capture_output=True,
                check=False,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
            stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
            _write_evidence(stdout_path, stdout)
            _write_evidence(stderr_path, stderr)
            _write_evidence(
                diagnostics_path,
                json.dumps(
                    {
                        "project_path": project_path,
                        "status": "timeout",
                        "timeout_seconds": timeout,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            raise BuildTimeoutExpired(project_path, timeout) from None
        except OSError as error:
            _write_evidence(stdout_path, "")
            _write_evidence(stderr_path, str(error))
            _write_evidence(
                diagnostics_path,
                json.dumps(
                    {
                        "project_path": project_path,
                        "status": "launch-error",
                        "error": str(error),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            raise

        _write_evidence(stdout_path, result.stdout or "")
        _write_evidence(stderr_path, result.stderr or "")
        if result.returncode != 0:
            _write_evidence(
                diagnostics_path,
                json.dumps(
                    {
                        "project_path": project_path,
                        "status": "failed",
                        "returncode": result.returncode,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            raise BuildError(project_path, result.stdout or "") from None

        packages = tuple(sorted((full_project_path / "output").glob("*.app"), key=lambda path: str(path).casefold()))
        if len(packages) != 1:
            _write_evidence(
                diagnostics_path,
                json.dumps(
                    {
                        "project_path": project_path,
                        "status": "invalid-package-output",
                        "package_paths": [str(package) for package in packages],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            raise BuildError(project_path, f"Expected exactly one produced .app package, found {len(packages)}.")

        package_path = packages[0]
        package_hash = _sha256_file(package_path)
        _write_evidence(
            diagnostics_path,
            json.dumps(
                {
                    "package_hash": package_hash,
                    "package_path": str(package_path),
                    "project_path": project_path,
                    "returncode": result.returncode,
                    "status": "published",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        records.append(
            ProjectBuildEvidence(
                project_path=project_path,
                command_path=command_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                diagnostics_path=diagnostics_path,
                package_path=package_path,
                package_hash=package_hash,
            )
        )

    return ProjectPublicationEvidence(tuple(records))


def run_tests(entry: _BugFixTestGenBase, container: ContainerConfig, repo_path: Path) -> TestRunSummary:
    try:
        summaries: list[TestRunSummary] = []
        if entry.fail_to_pass:
            logger.info(f"Running {len(entry.fail_to_pass)} fail-to-pass tests")
            summaries.append(run_test_suite(entry.fail_to_pass, TestExpectation.ALL_PASS, container, repo_path))

        if entry.pass_to_pass:
            logger.info(f"Running {len(entry.pass_to_pass)} pass-to-pass tests")
            summaries.append(run_test_suite(entry.pass_to_pass, TestExpectation.ALL_PASS, container, repo_path))

        logger.info("All tests completed")
        combined = TestRunSummary.combine(summaries)
        combined.require(TestExpectation.ALL_PASS)
    except TestExecutionError as error:
        if error.failure_kind is TestExecutionFailureKind.OUTCOME:
            raise
        raise TestInfrastructureError(
            error.expectation,
            reason=error.reason,
            stdout=error.stdout,
            stderr=error.stderr,
            summary=error.summary,
        ) from error
    return combined


def _normalize_test_entries(test_entries: list[TestEntry]) -> list[TestEntry]:
    functions_by_codeunit: dict[int, set[str]] = {}
    for entry in test_entries:
        functions_by_codeunit.setdefault(entry.codeunitID, set()).update(entry.functionName)
    return [TestEntry(codeunitID=codeunit_id, functionName=frozenset(function_names)) for codeunit_id, function_names in sorted(functions_by_codeunit.items())]


def _serialize_test_entries(test_entries: list[TestEntry]) -> str:
    serializable_entries = [{"codeunitID": entry.codeunitID, "functionName": sorted(entry.functionName)} for entry in test_entries]
    return json.dumps(serializable_entries, separators=(",", ":"))


def run_test_suite(
    test_entries: list[TestEntry],
    expectation: TestExpectation,
    container: ContainerConfig,
    repo_path: Path,
) -> TestRunSummary:
    with tempfile.TemporaryDirectory(prefix=".bcbench-test-evidence-", dir=repo_path) as evidence_directory:
        return run_test_suite_with_evidence(
            test_entries,
            expectation,
            container,
            repo_path,
            Path(evidence_directory),
        ).summary


def run_test_suite_with_evidence(
    test_entries: list[TestEntry],
    expectation: TestExpectation,
    container: ContainerConfig,
    repo_path: Path,
    evidence_directory: Path,
) -> TestSuiteEvidence:
    normalized_entries = _normalize_test_entries(test_entries)
    test_entries_json = _serialize_test_entries(normalized_entries)
    evidence_path = _prepare_evidence_directory(evidence_directory)
    ps_script = build_ps_dataset_tests_script(
        container.name,
        container.username,
        container.password,
        test_entries_json,
        evidence_path,
    )
    command_path = _write_evidence(evidence_path / "command.json", _redacted_command(ps_script, container.password))
    stdout_path = evidence_path / "stdout.txt"
    stderr_path = evidence_path / "stderr.txt"
    logger.info(f"Running test suite with expectation: {expectation}")
    logger.info(f"Tests to run: {test_entries_json}")
    try:
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            cwd=repo_path,
            capture_output=True,
            check=False,
            text=True,
            timeout=_config.timeout.test_execution,
        )
    except subprocess.TimeoutExpired as error:
        logger.exception(f"Test execution timed out after {_config.timeout.test_execution} seconds")
        timeout_error = TestExecutionTimeoutExpired(test_entries_json, _config.timeout.test_execution)
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
        _write_evidence(stdout_path, stdout)
        _write_evidence(stderr_path, stderr)
        raise TestInfrastructureError(
            expectation,
            reason=f"Business Central test execution timed out after {_config.timeout.test_execution} seconds",
            stdout=stdout,
            stderr=stderr,
        ) from timeout_error
    except OSError as error:
        _write_evidence(stdout_path, "")
        _write_evidence(stderr_path, str(error))
        raise TestInfrastructureError(
            expectation,
            reason=f"Failed to launch Business Central test execution infrastructure: {error}",
        ) from error

    _write_evidence(stdout_path, result.stdout or "")
    _write_evidence(stderr_path, result.stderr or "")
    if result.stdout:
        logger.debug(f"Test output:\n{result.stdout}")

    try:
        summary = load_test_run_summary(evidence_path, normalized_entries)
    except (OSError, ValueError, ET.ParseError) as error:
        raise TestInfrastructureError(
            expectation,
            stderr=result.stderr,
            stdout=result.stdout,
            reason=f"Invalid test evidence: {error}",
        ) from error

    if result.returncode != 0:
        raise TestInfrastructureError(
            expectation,
            stderr=result.stderr,
            stdout=result.stdout,
            reason="Business Central test execution failed before evidence validation",
            summary=summary,
        )

    try:
        summary.require(expectation)
    except TestExecutionError as error:
        raise TestExecutionError(
            error.expectation,
            stderr=result.stderr,
            stdout=result.stdout,
            reason=error.reason,
            summary=error.summary,
            failure_kind=error.failure_kind,
        ) from error
    logger.info(f"Test suite completed with expectation met: {expectation}")
    return TestSuiteEvidence(
        summary=summary,
        command_path=command_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        discovery_paths=tuple(sorted(evidence_path.glob("discovery-*.json"), key=lambda path: path.name)),
        junit_paths=tuple(sorted(evidence_path.glob("results-*.xml"), key=lambda path: path.name)),
    )


# --- data-query category: compile + run an AL query and capture its rows via a wrapped API query ---

# API metadata injected into a generated/gold query so it is exposed over OData and can be fetched.
_QUERY_API_PUBLISHER = "bcbench"
_QUERY_API_GROUP = "eval"
_QUERY_API_VERSION = "v1.0"


def _safe_object_name(object_id: int) -> str:
    """A short, unique, always-valid query object name.

    The object name is irrelevant to a query's result set (we score by comparing data, not
    identifiers), but AL requires it to be a valid identifier of <=30 characters and unique in
    the tenant. Normalizing it keeps the benchmark focused on query logic instead of failing an
    otherwise-correct query just because the agent chose a long/descriptive name (AL0305).
    """
    return f"BCBenchQuery{object_id}"


def _entity_set_name(object_id: int) -> str:
    """Per-object OData entity set so the generated and gold API queries don't collide on route."""
    return f"bcbenchResults{object_id}"


def _entity_name(object_id: int) -> str:
    return f"bcbenchResult{object_id}"


def _query_api_properties(object_id: int) -> str:
    return (
        "QueryType = API;\n"
        f"    APIPublisher = '{_QUERY_API_PUBLISHER}';\n"
        f"    APIGroup = '{_QUERY_API_GROUP}';\n"
        f"    APIVersion = '{_QUERY_API_VERSION}';\n"
        f"    EntityName = '{_entity_name(object_id)}';\n"
        f"    EntitySetName = '{_entity_set_name(object_id)}';"
    )


def wrap_query_as_api(query_text: str, object_id: int) -> str:
    """Turn a plain AL query object into an API query the harness can fetch over OData.

    Reassigns the object id and normalizes the object name (so generated and gold apps don't
    collide and long names don't cause AL0305), drops any existing ``QueryType`` line, and
    injects the API properties right after the object's opening brace. Pure string transform so
    it can be unit-tested without a container.
    """
    import re

    safe_name = _safe_object_name(object_id)
    # AL keywords are case-insensitive; match `query`/`QueryType` in any casing.
    text, replaced = re.subn(
        r'(\bquery\s+)\d+\s+("(?:[^"\\]|\\.)*"|\w+)',
        rf"\g<1>{object_id} {safe_name}",
        query_text,
        count=1,
        flags=re.IGNORECASE,
    )
    if replaced == 0:
        raise BuildError("query-wrap", f"No AL query object declaration found in generated output:\n{query_text}")

    text = re.sub(r"\bQueryType\s*=\s*\w+\s*;", "", text, count=1, flags=re.IGNORECASE)

    brace_index = text.find("{")
    if brace_index == -1:
        raise BuildError("query-wrap", f"Generated query has no object body ('{{' not found):\n{query_text}")
    return f"{text[: brace_index + 1]}\n    {_query_api_properties(object_id)}\n{text[brace_index + 1 :]}"


# The gold/generated query is compiled, published and read in four clearly-delimited, individually
# logged phases. This whole script runs as one opaque `pwsh -Command` blob, so without the phase
# markers a failure or timeout is unattributable; `Write-QueryPhase` prints a timestamped
# `[query-<suffix>] Phase N/4: ...` line so a CI run shows exactly which phase it reached.
_QUERY_RUN_TEMPLATE = Template(
    """
Import-Module BcContainerHelper -Force -DisableNameChecking
Import-Module '$app_utils_path' -Force
$$ErrorActionPreference = 'Stop'

function Write-QueryPhase([string]$$phase) {
    Write-Host "[query-$suffix] $$((Get-Date).ToString('HH:mm:ss')) $$phase"
}

$$password = ConvertTo-SecureString '$password' -AsPlainText -Force
$$credential = New-Object System.Management.Automation.PSCredential('$username', $$password)

# --- Phase 1/4: cleanup ---
# Remove any app left installed by a previous run of the same suffix so re-running against the
# same container doesn't fail with an object-ID conflict on the fixed 50100/50101 range.
Write-QueryPhase 'Phase 1/4: removing any app from a prior run'
UnInstall-BcContainerApp -containerName '$container_name' -name '$app_name' -publisher '$app_publisher' -force -doNotSaveData -ErrorAction SilentlyContinue
UnPublish-BcContainerApp -containerName '$container_name' -name '$app_name' -publisher '$app_publisher' -ErrorAction SilentlyContinue

# --- Phase 2/4: compile + publish ---
# Compile + publish the wrapped API query with the same proven helper the other categories use
# (clears/sets an explicit .alpackages symbol folder, GenerateReportLayout=No, ForceSync,
# dependencyPublishingOption=ignore) so Base Application symbols resolve reliably.
Write-QueryPhase 'Phase 2/4: compiling + publishing the wrapped API query'
Invoke-AppBuildAndPublish -containerName '$container_name' -appProjectFolder '$app_dir' -credential $$credential -skipVerification -useDevEndpoint

try {
    # --- Phase 3/4: read rows ---
    # Read the query's rows over the OData/API endpoint from *inside* the container, so we don't depend
    # on host->container name resolution or published ports (the runner does not update its hosts file).
    # Basic auth header is built by hand rather than via -Credential: PowerShell 7 (used inside the
    # container) refuses -Credential over plain HTTP, and a manual header works on both 5.1 and 7.
    Write-QueryPhase 'Phase 3/4: reading rows over the OData endpoint'
    $$json = Invoke-ScriptInBcContainer -containerName '$container_name' -argumentList $$credential, '$publisher', '$group', '$version', '$entity_set', '$company' -scriptblock {
        param($$cred, $$pub, $$grp, $$ver, $$eset, $$company)
        $$pair = "$$($$cred.UserName):$$($$cred.GetNetworkCredential().Password)"
        $$headers = @{ Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($$pair)) }
        $$base = 'http://localhost:7048/BC/api'
        # Pin the gold query to the company the agent queried via MCP so the comparison is against the
        # same data. The company is required upstream, so a missing one here is a hard error, not a
        # silent fall-through to an arbitrary company.
        $$companies = (Invoke-RestMethod -Uri "$$base/v2.0/companies" -Headers $$headers).value
        $$companyId = ($$companies | Where-Object { $$_.name -eq $$company } | Select-Object -First 1).id
        if (-not $$companyId) { throw "Company '$$company' not found among $$($$companies.name -join ', ')" }
        # Follow @odata.nextLink so large result sets aren't silently truncated to the first page.
        $$rows = [System.Collections.Generic.List[object]]::new()
        $$uri = "$$base/$$pub/$$grp/$$ver/companies($$companyId)/$$eset"
        while ($$uri) {
            $$page = Invoke-RestMethod -Uri $$uri -Headers $$headers
            if ($$null -ne $$page.value) { foreach ($$row in $$page.value) { $$rows.Add($$row) } }
            $$uri = $$page.'@odata.nextLink'
        }
        $$rows | ConvertTo-Json -Depth 10 -Compress
    }
    $$json | Out-File -FilePath '$result_file' -Encoding utf8
    Write-QueryPhase 'Phase 3/4: rows written'
}
finally {
    # --- Phase 4/4: teardown ---
    # Best-effort teardown so the container doesn't accumulate throwaway apps between runs.
    Write-QueryPhase 'Phase 4/4: tearing down the throwaway app'
    UnInstall-BcContainerApp -containerName '$container_name' -name '$app_name' -publisher '$app_publisher' -force -doNotSaveData -ErrorAction SilentlyContinue
    UnPublish-BcContainerApp -containerName '$container_name' -name '$app_name' -publisher '$app_publisher' -ErrorAction SilentlyContinue
}
""".strip()
)


def execute_al_query(query_text: str, container: ContainerConfig, version: str, work_root: Path, suffix: Literal["generated", "gold"], company: str) -> list[dict]:
    """Compile + publish an AL query (wrapped as an API query) to the container and return its rows.

    Builds a throwaway app under ``work_root/.bcbench-query-<suffix>``, compiles + publishes it,
    then reads the query's OData endpoint. ``company`` pins which company the query runs against (so
    the gold matches the company the agent queried via MCP) and is required — the query must run
    against a known company, never an arbitrary default. Raises :class:`BuildError` if the query does
    not compile or publish.

    NOTE: the container-side steps (compile/publish/OData fetch) require a running BC container
    and have not been validated locally; the wrapping and comparison logic are unit-tested.
    """
    import json

    object_id = 50100 if suffix == "generated" else 50101
    app_dir = work_root / f".bcbench-query-{suffix}"
    if app_dir.exists():
        remove_tree(app_dir)

    app_name = f"BC-Bench Query {suffix}"
    app_publisher = "BC-Bench"
    bootstrap_app_json(app_dir, app_name, version, id_range=(object_id, object_id), publisher=app_publisher)
    (app_dir / "query.al").write_text(wrap_query_as_api(query_text, object_id), encoding="utf-8")
    # Symbols are downloaded into an explicit .alpackages folder by Invoke-AppBuildAndPublish (below).

    result_file = app_dir / "result.json"
    app_utils_path = _config.paths.ps_script_path / "AppUtils.psm1"
    ps_script = _QUERY_RUN_TEMPLATE.substitute(
        app_utils_path=_escape_ps_string(str(app_utils_path)),
        suffix=suffix,
        container_name=_escape_ps_string(container.name),
        username=_escape_ps_string(container.username),
        password=_escape_ps_string(container.password),
        app_dir=_escape_ps_string(str(app_dir)),
        app_name=_escape_ps_string(app_name),
        app_publisher=_escape_ps_string(app_publisher),
        publisher=_QUERY_API_PUBLISHER,
        group=_QUERY_API_GROUP,
        version=_QUERY_API_VERSION,
        entity_set=_entity_set_name(object_id),
        result_file=_escape_ps_string(str(result_file)),
        company=_escape_ps_string(company),
    )

    try:
        subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            cwd=work_root,
            capture_output=True,
            check=True,
            text=True,
            timeout=_config.timeout.execute_query,
        )
    except subprocess.CalledProcessError as e:
        logger.debug(f"Query compile/publish/fetch failed ({suffix}): {e.stdout}\n{e.stderr}")
        raise BuildError(f"query-{suffix}", (e.stdout or "") + (e.stderr or "")) from None
    except subprocess.TimeoutExpired:
        raise BuildTimeoutExpired(f"query-{suffix}", _config.timeout.execute_query) from None

    rows = json.loads(result_file.read_text(encoding="utf-8-sig") or "[]")
    return rows if isinstance(rows, list) else [rows]
