import base64
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
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
        module_path: Path | None = None,
        timeout_seconds: int = 900,
    ) -> None:
        self._paths = validate_lifecycle_paths(paths)
        self._evidence_store = evidence_store
        self._powershell_runner = powershell_runner
        self._container_name = _required_value(container_name, "container_name")
        self._container_id = _required_value(container_id, "container_id")
        self._invocation_id = _required_value(invocation_id, "invocation_id")
        self._module_path = absolute_path(module_path or Path(__file__).parents[4] / "scripts" / "BugFixLifecycle.psm1")
        self._timeout_seconds = timeout_seconds

    def capture(self, name: str, expected_apps: Sequence[AppInventoryEntry]) -> CheckpointManifest:
        safe_name = _safe_name(name)
        expected = _normalized_apps(expected_apps)
        staging_directory = self._paths.mounted_staging / f"{safe_name}-capture"
        primary_error: CheckpointInfrastructureError | None = None
        manifest: CheckpointManifest | None = None
        try:
            payload = self._invoke_json(
                "capture",
                self._capture_script(safe_name, staging_directory),
            )
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
        except CheckpointInfrastructureError as exc:
            primary_error = exc
            raise
        except (OSError, ValueError) as exc:
            primary_error = CheckpointInfrastructureError(f"Checkpoint capture failed: {exc}")
            raise primary_error from exc
        finally:
            self._cleanup_staging(staging_directory, primary_error)
        if manifest is None:
            raise CheckpointInfrastructureError("Checkpoint capture did not produce a manifest")
        return manifest

    def restore(self, manifest: CheckpointManifest, expected_apps: Sequence[AppInventoryEntry]) -> None:
        expected = _normalized_apps(expected_apps)
        self._validate_apps(manifest.apps, expected, "manifest application inventory")
        protected_backup = self._validated_protected_backup(manifest.backup_path)
        self._validate_hash(protected_backup, manifest.sha256, "protected checkpoint")
        self._validate_container_identity(manifest.container)
        reject_reparse_components(self._paths.mounted_staging, self._paths.entry_root)
        staging_directory = Path(tempfile.mkdtemp(prefix=f"{_safe_name(manifest.name)}-restore-", dir=self._paths.mounted_staging))
        primary_error: CheckpointInfrastructureError | None = None
        try:
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
            payload = self._invoke_json("restore", self._restore_script(staged_manifest))
            self._validate_restore(payload, manifest, expected)
        except CheckpointInfrastructureError as exc:
            primary_error = exc
            raise
        except (OSError, ValueError) as exc:
            primary_error = CheckpointInfrastructureError(f"Checkpoint restore failed: {exc}")
            raise primary_error from exc
        finally:
            self._cleanup_staging(staging_directory, primary_error)

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
                "$credential = $null",
                "if ($env:BCBENCH_EVALUATOR_USERNAME -and $env:BCBENCH_EVALUATOR_PASSWORD) {",
                "    $securePassword = ConvertTo-SecureString $env:BCBENCH_EVALUATOR_PASSWORD -AsPlainText -Force",
                "    $credential = [PSCredential]::new($env:BCBENCH_EVALUATOR_USERNAME, $securePassword)",
                "}",
                "$result = Restore-BCBenchCheckpoint `",
                f"    -ContainerName {_ps_quote(self._container_name)} `",
                f"    -ExpectedContainerId {_ps_quote(self._container_id)} `",
                f"    -ExpectedInvocationId {_ps_quote(self._invocation_id)} `",
                "    -Manifest $manifest `",
                "    -Credential $credential `",
                "    -Company $env:BCBENCH_COMPANY `",
                f"    -TimeoutSeconds {self._timeout_seconds}",
                "$result | ConvertTo-Json -Compress -Depth 12",
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
        if payload.get("database_name") != manifest.database_name or payload.get("database_folder") != str(manifest.database_folder):
            raise CheckpointInfrastructureError("Checkpoint restore database topology mismatch")
        for field, description in (
            ("database_online", "database is not online"),
            ("service_restarted", "service was not genuinely restarted"),
            ("company_endpoint_ready", "company/auth endpoint is not ready"),
            ("test_discovery_ready", "test discovery is not responsive"),
        ):
            if payload.get(field) is not True:
                raise CheckpointInfrastructureError(f"Checkpoint restore verification failed: {description}")

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
        primary_error: CheckpointInfrastructureError | None,
    ) -> None:
        if not staging_directory.exists():
            return
        try:
            require_strict_descendant(staging_directory, self._paths.mounted_staging, "staging directory", "mounted staging root")
            reject_reparse_components(staging_directory, self._paths.entry_root)
            shutil.rmtree(staging_directory)
        except (OSError, ValueError) as exc:
            prefix = f"{primary_error}. " if primary_error is not None else ""
            raise CheckpointInfrastructureError(f"{prefix}Checkpoint staging cleanup failed: {exc}") from exc


def _normalized_apps(apps: Sequence[AppInventoryEntry]) -> tuple[AppInventoryEntry, ...]:
    return tuple(
        sorted(
            apps,
            key=lambda app: (
                app.app_id.casefold(),
                app.publisher.casefold(),
                app.name.casefold(),
                app.version,
                app.package_id.casefold(),
                app.scope.casefold(),
                app.installed,
                app.synchronized,
                app.content_hash,
            ),
        )
    )


def _required_value(value: str, name: str) -> str:
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _safe_name(name: str) -> str:
    if not name or name in {".", ".."} or any(character in name for character in ("/", "\\", ":", "\0")):
        raise CheckpointInfrastructureError(f"Invalid checkpoint name: {name!r}")
    return name


def _ps_quote(value: str | Path) -> str:
    return f"'{str(value).replace("'", "''")}'"


def _diagnostics(stdout: str, stderr: str) -> str:
    combined = "\n".join(part.strip() for part in (stdout, stderr) if part.strip())
    return combined[-4000:] or "no diagnostics"
