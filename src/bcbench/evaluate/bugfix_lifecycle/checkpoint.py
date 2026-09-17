import base64
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Protocol

from bcbench.evaluate.bugfix_lifecycle.evidence import EvidenceStore, sha256_file
from bcbench.evaluate.bugfix_lifecycle.models import (
    AppInventoryEntry,
    BugFixLifecyclePaths,
    CheckpointManifest,
    ContainerIdentity,
)
from bcbench.evaluate.bugfix_lifecycle.path_safety import (
    absolute_path,
    reject_reparse_components,
    require_strict_descendant,
    validate_lifecycle_paths,
)
from bcbench.exceptions import CheckpointInfrastructureError


class PowerShellResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


PowerShellRunner = Callable[[str], PowerShellResult]


class CheckpointManager:
    def __init__(
        self,
        paths: BugFixLifecyclePaths,
        evidence_store: EvidenceStore,
        powershell_runner: PowerShellRunner,
        *,
        container_name: str,
        container_id: str,
        invocation_id: str,
        expected_company: str,
        module_path: Path | None = None,
        timeout_seconds: int = 900,
        poll_interval_seconds: int = 5,
    ) -> None:
        self._paths = validate_lifecycle_paths(paths)
        self._evidence_store = evidence_store
        self._powershell_runner = powershell_runner
        self._container_name = _required_value(container_name, "container_name")
        self._container_id = _required_value(container_id, "container_id")
        self._invocation_id = _required_value(invocation_id, "invocation_id")
        self._expected_company = _required_value(expected_company, "expected_company")
        self._module_path = absolute_path(module_path or Path(__file__).parents[4] / "scripts" / "BugFixLifecycle.psm1")
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds

    def capture(self, name: str, expected_apps: Sequence[AppInventoryEntry]) -> CheckpointManifest:
        safe_name = _safe_name(name)
        expected = _normalized_apps(expected_apps)
        staging_directory: Path | None = None
        primary_error: BaseException | None = None
        primary_traceback = None
        restart_error: BaseException | None = None
        cleanup_error: BaseException | None = None
        manifest: CheckpointManifest | None = None
        captured: CheckpointManifest | None = None
        service: Mapping[str, object] | None = None
        service_stopped = False
        capture_started = False
        capture_completed = False
        try:
            reject_reparse_components(self._paths.mounted_staging, self._paths.entry_root)
            staging_directory = Path(tempfile.mkdtemp(prefix=f"{safe_name}-capture-", dir=self._paths.mounted_staging))
            capture_started = True
            payload = self._invoke_json(
                "capture",
                self._capture_script(safe_name, staging_directory),
            )
            service_value = payload.get("service")
            if isinstance(service_value, Mapping):
                service = service_value
                service_stopped = service.get("state") == "Stopped"
            self._validate_capture_service(payload)
            captured = self._parse_manifest(payload, "capture")
            self._validate_capture_name(captured.name, safe_name)
            staging_backup = self._validated_staging_backup(captured.backup_path, staging_directory)
            self._validate_hash(staging_backup, captured.sha256, "captured backup")
            self._validate_container_identity(captured.container)
            self._validate_apps(captured.apps, expected, "captured application inventory")
            protected_backup = self._protect_backup(safe_name, staging_backup, captured.sha256)
            manifest = CheckpointManifest(
                name=safe_name,
                backup_path=protected_backup,
                sha256=captured.sha256,
                database_name=captured.database_name,
                database_folder=captured.database_folder,
                container=captured.container,
                apps=captured.apps,
            )
            self._evidence_store.save_checkpoint_manifest(safe_name, manifest.to_dict())
            capture_completed = True
        except BaseException as exc:  # noqa: BLE001 - recovery must run before interrupts propagate
            primary_error = exc
            primary_traceback = exc.__traceback__
        finally:
            try:
                if staging_directory is not None:
                    try:
                        self._cleanup_staging(staging_directory, _classified_primary_error("capture", primary_error))
                    except BaseException as exc:  # noqa: BLE001 - recovery must run after cleanup interrupts
                        cleanup_error = exc
            finally:
                try:
                    if service_stopped and service is not None:
                        if captured is None:
                            payload = self._invoke_json("capture restart", self._capture_recovery_script(service))
                            self._validate_capture_recovery(payload)
                        else:
                            payload = self._invoke_json(
                                "capture restart",
                                self._capture_completion_script(captured, service),
                            )
                            self._validate_restore(payload, captured, expected)
                    elif capture_started and not capture_completed:
                        payload = self._invoke_json("capture restart", self._service_recovery_script())
                        self._validate_capture_recovery(payload)
                except BaseException as exc:  # noqa: BLE001 - aggregate recovery failures with interrupts
                    restart_error = exc
        _raise_checkpoint_failures(
            "capture",
            primary_error=primary_error,
            primary_traceback=primary_traceback,
            restart_error=restart_error,
            cleanup_error=cleanup_error,
        )
        if manifest is None:
            raise CheckpointInfrastructureError("Checkpoint capture did not produce a manifest")
        return manifest

    def restore(
        self,
        manifest: CheckpointManifest,
        expected_apps: Sequence[AppInventoryEntry],
        *,
        on_restored: Callable[[], None] | None = None,
    ) -> None:
        staging_directory: Path | None = None
        primary_error: BaseException | None = None
        primary_traceback = None
        restart_error: BaseException | None = None
        cleanup_error: BaseException | None = None
        restore_started = False
        restore_completed = False
        try:
            expected = _normalized_apps(expected_apps)
            self._validate_apps(manifest.apps, expected, "manifest application inventory")
            protected_backup = self._validated_protected_backup(manifest.backup_path)
            self._validate_hash(protected_backup, manifest.sha256, "protected checkpoint")
            self._validate_container_identity(manifest.container)
            reject_reparse_components(self._paths.mounted_staging, self._paths.entry_root)
            staging_directory = Path(tempfile.mkdtemp(prefix=f"{_safe_name(manifest.name)}-restore-", dir=self._paths.mounted_staging))
            staged_backup = staging_directory / protected_backup.name
            shutil.copyfile(protected_backup, staged_backup)
            self._validate_hash(staged_backup, manifest.sha256, "staged checkpoint")
            staged_manifest = CheckpointManifest(
                name=manifest.name,
                backup_path=staged_backup,
                sha256=manifest.sha256,
                database_name=manifest.database_name,
                database_folder=manifest.database_folder,
                container=manifest.container,
                apps=manifest.apps,
            )
            restore_started = True
            payload = self._invoke_json("restore", self._restore_script(staged_manifest))
            restore_completed = payload.get("service_restarted") is True
            self._validate_restore(payload, manifest, expected)
            restore_completed = True
        except BaseException as exc:  # noqa: BLE001 - recovery must run before interrupts propagate
            primary_error = exc
            primary_traceback = exc.__traceback__
        finally:
            try:
                if staging_directory is not None:
                    try:
                        self._cleanup_staging(staging_directory, _classified_primary_error("restore", primary_error))
                    except BaseException as exc:  # noqa: BLE001 - recovery must run after cleanup interrupts
                        cleanup_error = exc
            finally:
                try:
                    if restore_started and not restore_completed:
                        payload = self._invoke_json("restore restart", self._service_recovery_script())
                        self._validate_capture_recovery(payload)
                except BaseException as exc:  # noqa: BLE001 - aggregate recovery failures with interrupts
                    restart_error = exc
        _raise_checkpoint_failures(
            "restore",
            primary_error=primary_error,
            primary_traceback=primary_traceback,
            restart_error=restart_error,
            cleanup_error=cleanup_error,
        )
        if on_restored is not None:
            on_restored()

    def _capture_script(self, name: str, staging_directory: Path) -> str:
        return "\n".join(
            (
                "$ErrorActionPreference = 'Stop'",
                f"Import-Module {_ps_quote(self._module_path)} -Force",
                "$result = Backup-BCBenchCheckpoint `",
                f"    -Name {_ps_quote(name)} `",
                f"    -ContainerName {_ps_quote(self._container_name)} `",
                f"    -ExpectedContainerId {_ps_quote(self._container_id)} `",
                f"    -ExpectedInvocationId {_ps_quote(self._invocation_id)} `",
                f"    -StagingDirectory {_ps_quote(staging_directory)}",
                "$result | ConvertTo-Json -Compress -Depth 12",
            )
        )

    def _restore_script(self, manifest: CheckpointManifest) -> str:
        encoded_manifest = base64.b64encode(json.dumps(manifest.to_dict(), sort_keys=True).encode()).decode()
        return "\n".join(
            (
                "$ErrorActionPreference = 'Stop'",
                f"Import-Module {_ps_quote(self._module_path)} -Force",
                f"$manifestJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded_manifest}'))",
                "$manifest = $manifestJson | ConvertFrom-Json -Depth 12",
                *self._evaluator_environment_script(),
                "$result = Restore-BCBenchCheckpoint `",
                f"    -ContainerName {_ps_quote(self._container_name)} `",
                f"    -ExpectedContainerId {_ps_quote(self._container_id)} `",
                f"    -ExpectedInvocationId {_ps_quote(self._invocation_id)} `",
                "    -Manifest $manifest `",
                "    -Credential $credential `",
                "    -ExpectedCompany $company `",
                f"    -TimeoutSeconds {self._timeout_seconds} `",
                f"    -PollIntervalSeconds {self._poll_interval_seconds}",
                "$result | ConvertTo-Json -Compress -Depth 12",
            )
        )

    def _capture_completion_script(
        self,
        manifest: CheckpointManifest,
        service: Mapping[str, object],
    ) -> str:
        encoded_manifest = base64.b64encode(json.dumps(manifest.to_dict(), sort_keys=True).encode()).decode()
        server_instance = _required_mapping_string(service, "server_instance")
        previous_process_id = _required_mapping_int(service, "previous_process_id")
        return "\n".join(
            (
                "$ErrorActionPreference = 'Stop'",
                f"Import-Module {_ps_quote(self._module_path)} -Force",
                f"$manifestJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded_manifest}'))",
                "$manifest = $manifestJson | ConvertFrom-Json -Depth 12",
                *self._evaluator_environment_script(),
                "$started = Start-BCBenchServiceTier `",
                f"    -ContainerName {_ps_quote(self._container_name)} `",
                f"    -ExpectedContainerId {_ps_quote(self._container_id)} `",
                f"    -ExpectedInvocationId {_ps_quote(self._invocation_id)} `",
                f"    -ServerInstance {_ps_quote(server_instance)} `",
                f"    -PreviousProcessId {previous_process_id}",
                "$readiness = Test-BCBenchReadiness `",
                f"    -ContainerName {_ps_quote(self._container_name)} `",
                f"    -ExpectedContainerId {_ps_quote(self._container_id)} `",
                f"    -ExpectedInvocationId {_ps_quote(self._invocation_id)} `",
                "    -Credential $credential `",
                "    -ExpectedCompany $company `",
                "    -ExpectedContainerIdentity $manifest.container `",
                "    -ExpectedDatabaseName ([string]$manifest.database_name) `",
                "    -ExpectedDatabaseFolder ([string]$manifest.database_folder) `",
                "    -ExpectedAppInventory @($manifest.apps) `",
                f"    -TimeoutSeconds {self._timeout_seconds} `",
                f"    -PollIntervalSeconds {self._poll_interval_seconds}",
                "$result = [PSCustomObject][ordered]@{",
                "    container = $readiness.container",
                "    apps = $readiness.apps",
                "    database_name = [string]$readiness.database_name",
                "    database_folder = [string]$readiness.database_folder",
                "    database_online = [bool]$readiness.database_online",
                "    service_restarted = [bool]$started.restarted",
                "    company_endpoint_ready = [bool]$readiness.company_endpoint_ready",
                "    test_discovery_ready = [bool]$readiness.test_discovery_ready",
                "    test_count = [int]$readiness.test_count",
                "}",
                "$result | ConvertTo-Json -Compress -Depth 12",
            )
        )

    def _evaluator_environment_script(self) -> tuple[str, ...]:
        return (
            "$username = $env:BC_SERVER_USERNAME",
            "$password = $env:BC_SERVER_PASSWORD",
            "$company = $env:BC_COMPANY",
            "if ([string]::IsNullOrWhiteSpace($username)) { throw 'BC_SERVER_USERNAME is required.' }",
            "if ([string]::IsNullOrEmpty($password)) { throw 'BC_SERVER_PASSWORD is required.' }",
            "if ([string]::IsNullOrWhiteSpace($company)) { throw 'BC_COMPANY is required.' }",
            f"if ($company -cne {_ps_quote(self._expected_company)}) {{",
            "    throw 'BC_COMPANY does not match the checkpoint manager expected company.'",
            "}",
            "$securePassword = ConvertTo-SecureString $password -AsPlainText -Force",
            "$credential = [PSCredential]::new($username, $securePassword)",
        )

    def _capture_recovery_script(self, service: Mapping[str, object]) -> str:
        server_instance = _required_mapping_string(service, "server_instance")
        previous_process_id = _required_mapping_int(service, "previous_process_id")
        return "\n".join(
            (
                "$ErrorActionPreference = 'Stop'",
                f"Import-Module {_ps_quote(self._module_path)} -Force",
                "$started = Start-BCBenchServiceTier `",
                f"    -ContainerName {_ps_quote(self._container_name)} `",
                f"    -ExpectedContainerId {_ps_quote(self._container_id)} `",
                f"    -ExpectedInvocationId {_ps_quote(self._invocation_id)} `",
                f"    -ServerInstance {_ps_quote(server_instance)} `",
                f"    -PreviousProcessId {previous_process_id}",
                "[PSCustomObject]@{ service_restarted = [bool]$started.restarted } | ConvertTo-Json -Compress",
            )
        )

    def _service_recovery_script(self) -> str:
        return "\n".join(
            (
                "$ErrorActionPreference = 'Stop'",
                f"Import-Module {_ps_quote(self._module_path)} -Force",
                "Get-BCBenchContainerIdentity `",
                f"    -ContainerName {_ps_quote(self._container_name)} `",
                f"    -ExpectedContainerId {_ps_quote(self._container_id)} `",
                f"    -ExpectedInvocationId {_ps_quote(self._invocation_id)} | Out-Null",
                "Import-Module BcContainerHelper -RequiredVersion 6.1.18 -Force -DisableNameChecking",
                (f"$service = Invoke-ScriptInBcContainer -containerName {_ps_quote(self._container_id)} -ScriptBlock {{"),
                "    $instance = Get-NAVServerInstance | Select-Object -First 1",
                "    if ($null -eq $instance) { throw 'No Business Central service tier instance was found.' }",
                '    $serviceName = "MicrosoftDynamicsNavServer`$$($instance.ServerInstance)"',
                "    $windowsService = Get-CimInstance Win32_Service -Filter \"Name='$serviceName'\"",
                "    [PSCustomObject]@{",
                "        server_instance = [string]$instance.ServerInstance",
                "        previous_process_id = if ($null -eq $windowsService) { 0 } else { [int]$windowsService.ProcessId }",
                "        state = [string]$instance.State",
                "    }",
                "}",
                "if ([string]$service.state -eq 'Stopped') {",
                "    $started = Start-BCBenchServiceTier `",
                f"        -ContainerName {_ps_quote(self._container_name)} `",
                f"        -ExpectedContainerId {_ps_quote(self._container_id)} `",
                f"        -ExpectedInvocationId {_ps_quote(self._invocation_id)} `",
                "        -ServerInstance ([string]$service.server_instance) `",
                "        -PreviousProcessId ([int]$service.previous_process_id)",
                "    [PSCustomObject]@{ service_restarted = [bool]$started.restarted } | ConvertTo-Json -Compress",
                "}",
                "elseif ([string]$service.state -eq 'Running') {",
                "    [PSCustomObject]@{ service_restarted = $true } | ConvertTo-Json -Compress",
                "}",
                "else {",
                "    throw \"Business Central service tier has unexpected state '$($service.state)'.\"",
                "}",
            )
        )

    def _invoke_json(self, operation: str, script: str) -> Mapping[str, object]:
        try:
            result = self._powershell_runner(script)
        except (OSError, subprocess.SubprocessError) as exc:
            raise CheckpointInfrastructureError(f"Checkpoint {operation} PowerShell invocation failed: {exc}") from exc
        if result.returncode != 0:
            diagnostics = _diagnostics(result.stdout, result.stderr)
            raise CheckpointInfrastructureError(f"Checkpoint {operation} PowerShell failed with exit code {result.returncode}: {diagnostics}")
        output_lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not output_lines:
            raise CheckpointInfrastructureError(f"Checkpoint {operation} PowerShell returned no JSON")
        try:
            payload = json.loads(output_lines[-1])
        except json.JSONDecodeError as exc:
            raise CheckpointInfrastructureError(f"Checkpoint {operation} PowerShell returned malformed JSON: {_diagnostics(result.stdout, result.stderr)}") from exc
        if not isinstance(payload, Mapping):
            raise CheckpointInfrastructureError(f"Checkpoint {operation} PowerShell JSON must be an object")
        return payload

    def _parse_manifest(self, payload: Mapping[str, object], operation: str) -> CheckpointManifest:
        try:
            return CheckpointManifest.from_dict(payload)
        except (TypeError, ValueError) as exc:
            raise CheckpointInfrastructureError(f"Checkpoint {operation} returned an invalid manifest: {exc}") from exc

    def _validate_capture_service(self, payload: Mapping[str, object]) -> None:
        service = payload.get("service")
        if not isinstance(service, Mapping):
            raise CheckpointInfrastructureError("Checkpoint capture returned no stopped service state")
        try:
            _required_mapping_string(service, "server_instance")
            _required_mapping_int(service, "previous_process_id")
        except (TypeError, ValueError) as exc:
            raise CheckpointInfrastructureError(f"Checkpoint capture returned invalid stopped service state: {exc}") from exc
        if service.get("state") != "Stopped":
            raise CheckpointInfrastructureError("Checkpoint capture did not leave the service tier stopped")

    def _validate_capture_recovery(self, payload: Mapping[str, object]) -> None:
        if payload.get("service_restarted") is not True:
            raise CheckpointInfrastructureError("Checkpoint capture recovery did not restart the service tier")

    def _validated_staging_backup(self, backup: Path, staging_directory: Path) -> Path:
        try:
            validated = require_strict_descendant(backup, self._paths.mounted_staging, "backup_path", "mounted staging root")
            reject_reparse_components(validated, self._paths.entry_root)
        except ValueError as exc:
            raise CheckpointInfrastructureError(f"Captured backup path is unsafe: {exc}") from exc
        expected_parent = absolute_path(staging_directory)
        if validated.parent != expected_parent:
            raise CheckpointInfrastructureError(f"Captured backup path {validated} must be an exact child of {expected_parent}")
        if not validated.is_file() or validated.is_symlink():
            raise CheckpointInfrastructureError(f"Captured backup is not a regular file: {validated}")
        return validated

    def _validated_protected_backup(self, backup: Path) -> Path:
        try:
            validated = require_strict_descendant(backup, self._paths.checkpoints, "backup_path", "protected checkpoint root")
            reject_reparse_components(validated, self._paths.protected_root)
        except ValueError as exc:
            raise CheckpointInfrastructureError(f"Checkpoint path is outside the protected checkpoint root: {exc}") from exc
        if not validated.is_file() or validated.is_symlink():
            raise CheckpointInfrastructureError(f"Protected checkpoint is not a regular file: {validated}")
        return validated

    def _protect_backup(self, name: str, source: Path, expected_hash: str) -> Path:
        destination_directory = self._paths.checkpoints / name
        reject_reparse_components(destination_directory, self._paths.protected_root)
        destination_directory.mkdir(parents=True, exist_ok=True)
        reject_reparse_components(destination_directory, self._paths.protected_root)
        destination = destination_directory / f"{expected_hash}.bak"
        if destination.exists():
            self._validate_hash(destination, expected_hash, "existing protected checkpoint")
            return destination
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination_directory, prefix=f".{expected_hash}.", suffix=".tmp", delete=False) as target:
                temporary = Path(target.name)
                with source.open("rb") as source_file:
                    shutil.copyfileobj(source_file, target)
                target.flush()
                os.fsync(target.fileno())
            self._validate_hash(temporary, expected_hash, "copied protected checkpoint")
            temporary.replace(destination)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._validate_hash(destination, expected_hash, "protected checkpoint")
        return destination

    def _validate_restore(
        self,
        payload: Mapping[str, object],
        manifest: CheckpointManifest,
        expected_apps: tuple[AppInventoryEntry, ...],
    ) -> None:
        container, apps = self._parse_restore_verification(payload)
        if container != manifest.container:
            raise CheckpointInfrastructureError("Checkpoint restore container identity mismatch")
        self._validate_apps(apps, expected_apps, "restored application inventory")
        if payload.get("database_name") != manifest.database_name or payload.get("database_folder") != manifest.database_folder:
            raise CheckpointInfrastructureError("Checkpoint restore database topology mismatch")
        for field, description in (
            ("database_online", "database is not online"),
            ("service_restarted", "service was not genuinely restarted"),
            ("company_endpoint_ready", "company/auth endpoint is not ready"),
            ("test_discovery_ready", "test discovery is not responsive"),
        ):
            if payload.get(field) is not True:
                raise CheckpointInfrastructureError(f"Checkpoint restore verification failed: {description}")
        test_count = payload.get("test_count")
        if not isinstance(test_count, int) or isinstance(test_count, bool) or test_count < 0:
            raise CheckpointInfrastructureError("Checkpoint restore verification returned invalid test discovery evidence")

    def _parse_restore_verification(
        self,
        payload: Mapping[str, object],
    ) -> tuple[ContainerIdentity, tuple[AppInventoryEntry, ...]]:
        container_value = payload.get("container")
        apps_value = payload.get("apps")
        if not isinstance(container_value, Mapping):
            raise CheckpointInfrastructureError("Checkpoint restore returned invalid verification: container identity is missing")
        if not isinstance(apps_value, list) or not all(isinstance(app, Mapping) for app in apps_value):
            raise CheckpointInfrastructureError("Checkpoint restore returned invalid verification: application inventory is missing")
        try:
            return ContainerIdentity.from_dict(container_value), tuple(AppInventoryEntry.from_dict(app) for app in apps_value)
        except (TypeError, ValueError) as exc:
            raise CheckpointInfrastructureError(f"Checkpoint restore returned invalid verification: {exc}") from exc

    def _validate_capture_name(self, actual: str, expected: str) -> None:
        if actual != expected:
            raise CheckpointInfrastructureError(f"Checkpoint capture returned name {actual!r}, expected {expected!r}")

    def _validate_container_identity(self, identity: ContainerIdentity) -> None:
        if identity.container_id != self._container_id:
            raise CheckpointInfrastructureError("Checkpoint container identity does not match the owned container")

    def _validate_hash(self, path: Path, expected_hash: str, description: str) -> None:
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise CheckpointInfrastructureError(f"{description} hash mismatch: expected {expected_hash}, got {actual_hash}")

    def _validate_apps(
        self,
        actual: Sequence[AppInventoryEntry],
        expected: Sequence[AppInventoryEntry],
        description: str,
    ) -> None:
        if _normalized_apps(actual) != _normalized_apps(expected):
            raise CheckpointInfrastructureError(f"Checkpoint {description} mismatch")

    def _cleanup_staging(
        self,
        staging_directory: Path,
        _primary_error: CheckpointInfrastructureError | None,
    ) -> None:
        if not staging_directory.exists():
            return
        try:
            require_strict_descendant(staging_directory, self._paths.mounted_staging, "staging directory", "mounted staging root")
            reject_reparse_components(staging_directory, self._paths.entry_root)
            shutil.rmtree(staging_directory)
        except (OSError, ValueError) as exc:
            raise CheckpointInfrastructureError(f"Checkpoint staging cleanup failed: {exc}") from exc


def _normalized_apps(apps: Sequence[AppInventoryEntry]) -> tuple[AppInventoryEntry, ...]:
    return tuple(
        sorted(
            apps,
            key=lambda app: (
                app.app_id,
                app.publisher,
                app.name,
                app.version,
                "" if app.package_id is None else app.package_id,
                app.scope,
                app.installed,
                app.synchronized,
                "" if app.content_hash is None else app.content_hash,
            ),
        )
    )


def _required_value(value: str, name: str) -> str:
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _required_mapping_string(value: Mapping[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{name} must be a non-empty string")
    return item


def _required_mapping_int(value: Mapping[str, object], name: str) -> int:
    item = value.get(name)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise TypeError(f"{name} must be a non-negative integer")
    return item


def _classified_primary_error(
    operation: str,
    error: BaseException | None,
) -> CheckpointInfrastructureError | None:
    if error is None:
        return None
    if isinstance(error, CheckpointInfrastructureError):
        return error
    if isinstance(error, (OSError, ValueError)):
        return CheckpointInfrastructureError(f"Checkpoint {operation} failed: {error}")
    return None


def _raise_checkpoint_failures(
    operation: str,
    *,
    primary_error: BaseException | None,
    primary_traceback: TracebackType | None,
    restart_error: BaseException | None,
    cleanup_error: BaseException | None,
) -> None:
    errors = tuple(error for error in (primary_error, restart_error, cleanup_error) if error is not None)
    if primary_error is not None and restart_error is None and cleanup_error is None:
        classified = _classified_primary_error(operation, primary_error)
        if classified is None:
            raise primary_error.with_traceback(primary_traceback)
        if classified is primary_error:
            raise classified.with_traceback(primary_traceback)
        raise classified from primary_error

    if not errors:
        return

    messages = []
    if primary_error is not None:
        messages.append(_checkpoint_failure_message(operation, primary_error, primary=True))
    if restart_error is not None:
        messages.append(_checkpoint_recovery_failure_message(operation, "restart", restart_error))
    if cleanup_error is not None:
        messages.append(_checkpoint_recovery_failure_message(operation, "staging cleanup", cleanup_error))
    combined = CheckpointInfrastructureError(". ".join(messages))
    if len(errors) == 1:
        if not isinstance(errors[0], Exception):
            raise errors[0].with_traceback(errors[0].__traceback__)
        raise combined from errors[0]
    if any(not isinstance(error, Exception) for error in errors):
        raise BaseExceptionGroup(". ".join(messages), errors)
    raise combined from ExceptionGroup(f"Checkpoint {operation} failures", errors)


def _checkpoint_failure_message(operation: str, error: BaseException, *, primary: bool) -> str:
    if primary:
        classified = _classified_primary_error(operation, error)
        if classified is not None:
            return str(classified)
        return f"Checkpoint {operation} failed unexpectedly: {error}"
    return str(error)


def _checkpoint_recovery_failure_message(operation: str, recovery: str, error: BaseException) -> str:
    if isinstance(error, CheckpointInfrastructureError):
        return str(error)
    return f"Checkpoint {operation} {recovery} failed: {error}"


def _safe_name(name: str) -> str:
    if not name or name in {".", ".."} or any(character in name for character in ("/", "\\", ":", "\0")):
        raise CheckpointInfrastructureError(f"Invalid checkpoint name: {name!r}")
    return name


def _ps_quote(value: str | Path) -> str:
    return f"'{str(value).replace("'", "''")}'"


def _diagnostics(stdout: str, stderr: str) -> str:
    combined = "\n".join(part.strip() for part in (stdout, stderr) if part.strip())
    return combined[-4000:] or "no diagnostics"
