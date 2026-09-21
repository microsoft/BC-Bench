import base64
import json
import secrets
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from bcbench.dataset import TestEntry
from bcbench.evaluate.bugfix_lifecycle.models import AppInventoryEntry, CheckpointManifest, ProvisionedLifecycleResources
from bcbench.evaluate.bugfix_lifecycle.rehearsal import RehearsalFault, RehearsalProbe
from bcbench.exceptions import CheckpointInfrastructureError
from bcbench.operations.bc_operations import run_test_suite_with_evidence
from bcbench.operations.test_execution import TestExpectation
from bcbench.types import ContainerConfig


def evaluator_powershell(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", "if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'Native PowerShell 7 is required.' }\n" + script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=1200,
    )


def _string_keyed_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CheckpointInfrastructureError("Rehearsal inventory entry must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise CheckpointInfrastructureError("Rehearsal inventory entry keys must be strings")
        result[key] = item
    return result


class RehearsalExecutionGuard:
    def __init__(self) -> None:
        self._operations_safe = True

    @contextmanager
    def operation(self) -> Iterator[None]:
        if not self._operations_safe:
            raise CheckpointInfrastructureError("Rehearsal adapter shutdown is unverified; no further container operations are safe")
        try:
            yield
        except BaseException:
            # Only the outer contained worker can establish drainage after an interrupted operation.
            self._operations_safe = False
            raise

    def run(self, script: str) -> subprocess.CompletedProcess[str]:
        with self.operation():
            return evaluator_powershell(script)


class PowerShellRehearsalAdapter:
    def __init__(
        self,
        resources: ProvisionedLifecycleResources,
        container: ContainerConfig,
        s0: CheckpointManifest,
        output: Path,
        tests: tuple[TestEntry, ...],
        *,
        execution_guard: RehearsalExecutionGuard | None = None,
    ) -> None:
        self.resources = resources
        self.container = container
        self.s0 = s0
        self.output = output
        self.tests = tests
        self.probe_name = "BCBenchRehearsal_" + secrets.token_hex(16)
        self.fault = RehearsalFault.NONE
        self.fault_applied = False
        self._execution_guard = execution_guard or RehearsalExecutionGuard()
        self.module = resources.benchmark_root / "scripts" / "BugFixLifecycleRehearsal.psm1"

    def set_fault(self, fault: RehearsalFault) -> None:
        self.fault = fault
        if fault is not RehearsalFault.NONE:
            self.fault_applied = False

    def run(self, script: str) -> subprocess.CompletedProcess[str]:
        if self.fault is not RehearsalFault.NONE and "$result = Restore-BCBenchCheckpoint `" in script:
            if script.count("$result = Restore-BCBenchCheckpoint `") != 1:
                raise CheckpointInfrastructureError("Ambiguous restore adapter boundary")
            script = script.replace(
                "$result = Restore-BCBenchCheckpoint `",
                f"Import-Module '{str(self.module).replace(chr(39), chr(39) * 2)}' -Force -DisableNameChecking\n"
                f"$result = Restore-BCBenchRehearsalCheckpoint -Fault {self.fault.value} "
                f"-StagingRoot '{str(self.resources.paths.mounted_staging).replace(chr(39), chr(39) * 2)}' `",
            )
            self.fault_applied = True
        return self._execution_guard.run(script)

    def _invoke(self, body: str, app: AppInventoryEntry | None = None) -> dict[str, object]:
        config = {
            "ContainerName": self.resources.container_name,
            "ExpectedContainerId": self.resources.expected_container_id,
            "ExpectedInvocationId": self.resources.expected_container_invocation_id,
            "DatabaseName": self.s0.database_name,
            "DatabaseFolder": self.s0.database_folder,
            "ProbeName": self.probe_name,
        }
        encoded = base64.b64encode(json.dumps(config).encode()).decode()
        app_encoded = base64.b64encode(json.dumps(app.to_dict() if app else None).encode()).decode()
        script = f"""
$ErrorActionPreference = 'Stop'
Import-Module '{str(self.module).replace("'", "''")}' -Force -DisableNameChecking
Import-Module '{str(self.module.with_name("BugFixLifecycle.psm1")).replace("'", "''")}' -Force -DisableNameChecking
$probe = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')) | ConvertFrom-Json -AsHashtable
$app = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{app_encoded}')) | ConvertFrom-Json
$owned = @{{ContainerName=$probe.ContainerName; ExpectedContainerId=$probe.ExpectedContainerId; ExpectedInvocationId=$probe.ExpectedInvocationId}}
if ([string]::IsNullOrWhiteSpace($env:BC_SERVER_USERNAME) -or [string]::IsNullOrWhiteSpace($env:BC_SERVER_PASSWORD) -or [string]::IsNullOrWhiteSpace($env:BC_COMPANY)) {{
    throw 'Evaluator credential environment is incomplete.'
}}
$credential = [PSCredential]::new($env:BC_SERVER_USERNAME, (ConvertTo-SecureString $env:BC_SERVER_PASSWORD -AsPlainText -Force))
{body}
$result | ConvertTo-Json -Compress -Depth 20
"""
        result = self.run(script)
        if result.returncode:
            # Child output may contain credentials supplied by external tools; persist only typed diagnostics.
            raise CheckpointInfrastructureError("Rehearsal PowerShell adapter failed; inspect the owned container without exporting credentials")
        try:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError) as error:
            raise CheckpointInfrastructureError("Invalid rehearsal adapter JSON") from error
        if not isinstance(payload, dict):
            raise CheckpointInfrastructureError("Rehearsal adapter response is not an object")
        return payload

    def read_probe(self) -> RehearsalProbe:
        payload = self._invoke("""
$result = Invoke-BCBenchRehearsalProbe @probe -Mode Read
$discovered = @(Get-BCBenchRehearsalDiscovery @owned -Credential $credential -Company $env:BC_COMPANY)
$result | Add-Member -NotePropertyName discovered -NotePropertyValue $discovered
""")
        return RehearsalProbe.from_dict(payload)

    def read_inventory(self) -> tuple[AppInventoryEntry, ...]:
        payload = self._invoke("$result = @{ apps = @(Get-BCBenchAppInventory @owned) }")
        apps = payload.get("apps")
        if not isinstance(apps, list):
            raise CheckpointInfrastructureError("Rehearsal inventory response is invalid")
        return tuple(AppInventoryEntry.from_dict(_string_keyed_mapping(app)) for app in apps)

    def create_probe(self) -> None:
        self._invoke("Invoke-BCBenchRehearsalProbe @probe -Mode Create | Out-Null\n$result = @{ created = $true }")

    def mutate(self, app: AppInventoryEntry) -> None:
        self._invoke(
            """
Uninstall-BCBenchRehearsalTestApp @owned -App $app
Invoke-BCBenchRehearsalProbe @probe -Mode Mutate | Out-Null
$result = @{ mutated = $true }
""",
            app,
        )

    def test_evidence(self, iteration: int) -> tuple[Path, tuple[TestEntry, ...]]:
        tests = self.tests
        if not tests:
            codeunit, method = self.read_probe().discovered[0].split(":", 1)
            tests = (TestEntry(codeunitID=int(codeunit), functionName=frozenset({method})),)
        directory = self.output / f"test-evidence-{iteration:04d}"
        # Verify immutable ownership immediately before the production test operation.
        self._invoke("Assert-BCBenchContainerOwnership @owned -Operations @{} | Out-Null\n$result = @{ owned = $true }")
        with self._execution_guard.operation():
            run_test_suite_with_evidence(
                list(tests),
                TestExpectation.ALL_PASS,
                replace(self.container, name=self.resources.expected_container_id),
                self.resources.benchmark_root,
                directory,
            )
        return directory, tests
