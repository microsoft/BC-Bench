import json
import os
import re
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from bcbench.evaluate.bugfix_lifecycle import (
    AppInventoryEntry,
    BugFixLifecyclePaths,
    CheckpointManager,
    CheckpointManifest,
    ContainerIdentity,
    EvidenceStore,
    sha256_file,
)
from bcbench.exceptions import CheckpointInfrastructureError


def _paths(tmp_path: Path) -> BugFixLifecyclePaths:
    entry_root = tmp_path / "entry"
    protected_root = tmp_path / "protected"
    paths = BugFixLifecyclePaths(
        entry_root=entry_root,
        baseline_workspace=entry_root / "baseline",
        agent_workspace=entry_root / "agent",
        agent_logs=entry_root / "agent-logs",
        mounted_staging=entry_root / "staging",
        evaluator_workspaces=entry_root / "evaluators",
        evidence=entry_root / "evidence",
        protected_root=protected_root,
        trusted_source=protected_root / "repository.git",
        checkpoints=protected_root / "checkpoints",
        final_results=protected_root / "final-results",
    )
    for path in (paths.mounted_staging, paths.evidence, paths.checkpoints, paths.final_results):
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _app(
    *,
    content_hash: str | None = "a" * 64,
    name: str = "Library",
    package_id: str | None = "22222222-2222-2222-2222-222222222222",
) -> AppInventoryEntry:
    return AppInventoryEntry(
        app_id="11111111-1111-1111-1111-111111111111",
        name=name,
        publisher="Microsoft",
        version="1.2.3.4",
        package_id=package_id,
        scope="Global",
        installed=True,
        synchronized=True,
        content_hash=content_hash,
    )


def _identity(*, container_id: str = "container-id") -> ContainerIdentity:
    return ContainerIdentity(
        container_id=container_id,
        image_id="image-id",
        hostname="bc-checkpoint",
        mounts=("C:\\host-b:C:\\container-b", "C:\\host-a:C:\\container-a"),
    )


class FakePowerShellRunner:
    def __init__(self, paths: BugFixLifecyclePaths, app: AppInventoryEntry, identity: ContainerIdentity) -> None:
        self.paths = paths
        self.app = app
        self.identity = identity
        self.calls: list[str] = []
        self.capture_payload: dict[str, object] | None = None
        self.restore_payload: dict[str, object] | None = None
        self.capture_completion_payload: dict[str, object] | None = None
        self.returncode = 0
        self.stderr = ""

    def __call__(self, script: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(script)
        if "Backup-BCBenchCheckpoint" in script:
            match = re.search(r"-StagingDirectory '([^']+)'", script)
            assert match is not None
            staging = Path(match.group(1).replace("''", "'"))
            backup = staging / "database.bak"
            backup.write_bytes(b"verified database backup")
            payload = self.capture_payload or {
                "name": "baseline",
                "backup_path": str(backup),
                "sha256": sha256_file(backup),
                "database_name": "BC",
                "database_folder": "C:\\databases",
                "container": self.identity.to_dict(),
                "apps": [self.app.to_dict()],
                "service": {
                    "server_instance": "BC",
                    "previous_process_id": 100,
                    "state": "Stopped",
                },
            }
        elif "Restore-BCBenchCheckpoint" in script:
            payload = self.restore_payload or {
                "container": self.identity.to_dict(),
                "apps": [self.app.to_dict()],
                "database_name": "BC",
                "database_folder": "C:\\databases",
                "database_online": True,
                "service_restarted": True,
                "company_endpoint_ready": True,
                "test_discovery_ready": True,
                "test_count": 0,
            }
        else:
            payload = self.capture_completion_payload or {
                "container": self.identity.to_dict(),
                "apps": [self.app.to_dict()],
                "database_name": "BC",
                "database_folder": "C:\\databases",
                "database_online": True,
                "service_restarted": True,
                "company_endpoint_ready": True,
                "test_discovery_ready": True,
                "test_count": 0,
            }
        return subprocess.CompletedProcess(
            args=["pwsh"],
            returncode=self.returncode,
            stdout=json.dumps(payload),
            stderr=self.stderr,
        )


def _manager(tmp_path: Path) -> tuple[CheckpointManager, FakePowerShellRunner, BugFixLifecyclePaths, AppInventoryEntry]:
    paths = _paths(tmp_path)
    app = _app()
    runner = FakePowerShellRunner(paths, app, _identity())
    manager = CheckpointManager(
        paths,
        EvidenceStore(paths),
        runner,
        container_name="bc-checkpoint",
        container_id="container-id",
        invocation_id="invocation-id",
        expected_company="CRONUS",
    )
    return manager, runner, paths, app


def test_checkpoint_readiness_uses_setup_exported_evaluator_credentials_without_serializing_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    app = _app()
    identity = _identity()
    module_path = tmp_path / "CheckpointCredentialContract.psm1"
    module_path.write_text(
        f"""
$script:app = '{json.dumps(app.to_dict(), separators=(",", ":"))}' | ConvertFrom-Json
$script:identity = '{json.dumps(identity.to_dict(), separators=(",", ":"))}' | ConvertFrom-Json

function Backup-BCBenchCheckpoint {{
    param(
        [string]$Name,
        [string]$ContainerName,
        [string]$ExpectedContainerId,
        [string]$ExpectedInvocationId,
        [string]$StagingDirectory
    )
    $backupPath = Join-Path $StagingDirectory 'database.bak'
    [IO.File]::WriteAllBytes($backupPath, [Text.Encoding]::UTF8.GetBytes('verified database backup'))
    [PSCustomObject][ordered]@{{
        name = $Name
        backup_path = $backupPath
        sha256 = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash.ToLowerInvariant()
        database_name = 'BC'
        database_folder = 'C:\\databases'
        container = $script:identity
        apps = @($script:app)
        service = [PSCustomObject]@{{
            server_instance = 'BC'
            previous_process_id = 100
            state = 'Stopped'
        }}
    }}
}}

function Start-BCBenchServiceTier {{
    param(
        [string]$ContainerName,
        [string]$ExpectedContainerId,
        [string]$ExpectedInvocationId,
        [string]$ServerInstance,
        [int]$PreviousProcessId
    )
    [PSCustomObject]@{{ restarted = $true }}
}}

function Test-BCBenchReadiness {{
    param(
        [string]$ContainerName,
        [string]$ExpectedContainerId,
        [string]$ExpectedInvocationId,
        [PSCredential]$Credential,
        [string]$ExpectedCompany,
        [PSObject]$ExpectedContainerIdentity,
        [string]$ExpectedDatabaseName,
        [string]$ExpectedDatabaseFolder,
        [object[]]$ExpectedAppInventory,
        [int]$TimeoutSeconds,
        [int]$PollIntervalSeconds
    )
    if ($null -eq $Credential) {{ throw 'Readiness received a null credential.' }}
    if ($Credential.UserName -cne $env:BC_SERVER_USERNAME) {{ throw 'Readiness received the wrong username.' }}
    if ($Credential.GetNetworkCredential().Password -cne $env:BC_SERVER_PASSWORD) {{
        throw 'Readiness received the wrong password.'
    }}
    if ($ExpectedCompany -cne $env:BC_COMPANY) {{ throw 'Readiness received the wrong company.' }}
    [PSCustomObject][ordered]@{{
        container = $script:identity
        apps = @($script:app)
        database_name = $ExpectedDatabaseName
        database_folder = $ExpectedDatabaseFolder
        database_online = $true
        company_endpoint_ready = $true
        test_discovery_ready = $true
        test_count = 0
    }}
}}

function Restore-BCBenchCheckpoint {{
    param(
        [string]$ContainerName,
        [string]$ExpectedContainerId,
        [string]$ExpectedInvocationId,
        [PSObject]$Manifest,
        [PSCredential]$Credential,
        [string]$ExpectedCompany,
        [int]$TimeoutSeconds,
        [int]$PollIntervalSeconds
    )
    if ($null -eq $Credential) {{ throw 'Restore received a null credential.' }}
    if ($Credential.UserName -cne $env:BC_SERVER_USERNAME) {{ throw 'Restore received the wrong username.' }}
    if ($Credential.GetNetworkCredential().Password -cne $env:BC_SERVER_PASSWORD) {{
        throw 'Restore received the wrong password.'
    }}
    if ($ExpectedCompany -cne $env:BC_COMPANY) {{ throw 'Restore received the wrong company.' }}
    [PSCustomObject][ordered]@{{
        container = $script:identity
        apps = @($script:app)
        database_name = [string]$Manifest.database_name
        database_folder = [string]$Manifest.database_folder
        database_online = $true
        service_restarted = $true
        company_endpoint_ready = $true
        test_discovery_ready = $true
        test_count = 0
    }}
}}
""",
        encoding="utf-8",
    )
    password = "checkpoint-evaluator-secret"
    monkeypatch.setenv("BC_SERVER_USERNAME", "checkpoint-evaluator")
    monkeypatch.setenv("BC_SERVER_PASSWORD", password)
    monkeypatch.setenv("BC_COMPANY", "CRONUS")
    invocations: list[subprocess.CompletedProcess[str]] = []

    def powershell_runner(script: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            env={**os.environ},
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        invocations.append(result)
        return result

    manager = CheckpointManager(
        paths,
        EvidenceStore(paths),
        powershell_runner,
        container_name="bc-checkpoint",
        container_id=identity.container_id,
        invocation_id="invocation-id",
        expected_company="CRONUS",
        module_path=module_path,
    )

    manifest = manager.capture("baseline", (app,))
    manager.restore(manifest, (app,))

    assert len(invocations) == 3
    assert all(password not in " ".join(result.args) for result in invocations)
    assert all(password not in result.stdout for result in invocations)
    assert all(password not in result.stderr for result in invocations)
    assert password not in json.dumps(manifest.to_dict())
    assert all("BCBENCH_EVALUATOR_" not in " ".join(result.args) for result in invocations)


def test_checkpoint_models_are_immutable_and_json_paths_are_explicit(tmp_path: Path) -> None:
    backup = tmp_path / "checkpoint.bak"
    identity = _identity()
    manifest = CheckpointManifest(
        name="baseline",
        backup_path=backup,
        sha256="a" * 64,
        database_name="BC",
        database_folder="C:\\databases",
        container=identity,
        apps=(_app(),),
    )

    with pytest.raises(FrozenInstanceError):
        identity.hostname = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        manifest.name = "changed"  # type: ignore[misc]

    payload = manifest.to_dict()
    assert payload["backup_path"] == str(backup)
    assert payload["database_folder"] == "C:\\databases"
    assert payload["container"]["mounts"] == sorted(identity.mounts)
    assert CheckpointManifest.from_dict(payload) == manifest


def test_checkpoint_models_preserve_nullable_app_fields_and_string_database_folder(tmp_path: Path) -> None:
    app = _app(package_id=None, content_hash=None)
    manifest = CheckpointManifest(
        name="baseline",
        backup_path=tmp_path / "checkpoint.bak",
        sha256="A" * 64,
        database_name="BC",
        database_folder="C:\\databases",
        container=_identity(),
        apps=(app,),
    )

    assert manifest.database_folder == "C:\\databases"
    assert manifest.apps[0].package_id is None
    assert manifest.apps[0].content_hash is None
    assert CheckpointManifest.from_dict(manifest.to_dict()) == manifest


def test_capture_protects_backup_persists_manifest_and_removes_staging(tmp_path: Path) -> None:
    manager, runner, paths, app = _manager(tmp_path)

    manifest = manager.capture("baseline", (app,))

    assert manifest.backup_path.parent == paths.checkpoints / "baseline"
    assert manifest.backup_path.read_bytes() == b"verified database backup"
    assert manifest.sha256 == sha256_file(manifest.backup_path)
    assert not any(paths.mounted_staging.iterdir())
    persisted = json.loads((paths.evidence / "checkpoints" / "baseline.json").read_text(encoding="utf-8"))
    assert persisted == manifest.to_dict()
    assert len(runner.calls) == 2
    assert "Backup-BCBenchCheckpoint" in runner.calls[0]
    assert "Start-BCBenchServiceTier" in runner.calls[1]
    assert "Test-BCBenchReadiness" in runner.calls[1]
    assert "invocation-id" in runner.calls[0]


def test_capture_uses_unique_staging_without_deleting_preexisting_named_path(tmp_path: Path) -> None:
    manager, runner, paths, app = _manager(tmp_path)
    preexisting = paths.mounted_staging / "baseline-capture"
    preexisting.mkdir()
    marker = preexisting / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    first = manager.capture("baseline", (app,))
    second = manager.capture("baseline", (app,))

    staging_paths = [
        re.search(r"-StagingDirectory '([^']+)'", call).group(1)  # type: ignore[union-attr]
        for call in runner.calls
        if "Backup-BCBenchCheckpoint" in call
    ]
    assert len(set(staging_paths)) == 2
    assert marker.read_text(encoding="utf-8") == "keep"
    assert first == second


def test_capture_orders_protection_cleanup_restart_and_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager, runner, _, app = _manager(tmp_path)
    order: list[str] = []
    original_runner = runner.__call__
    original_protect = manager._protect_backup
    original_cleanup = manager._cleanup_staging

    def ordered_runner(script: str) -> subprocess.CompletedProcess[str]:
        if "Backup-BCBenchCheckpoint" in script:
            order.extend(("stop", "backup"))
        else:
            order.extend(("start", "ready"))
        return original_runner(script)

    def ordered_protect(name: str, source: Path, expected_hash: str) -> Path:
        order.append("protect")
        return original_protect(name, source, expected_hash)

    def ordered_cleanup(staging_directory: Path, primary_error: CheckpointInfrastructureError | None) -> None:
        order.append("clean")
        original_cleanup(staging_directory, primary_error)

    manager._powershell_runner = ordered_runner
    monkeypatch.setattr(manager, "_protect_backup", ordered_protect)
    monkeypatch.setattr(manager, "_cleanup_staging", ordered_cleanup)

    manager.capture("baseline", (app,))

    assert order == ["stop", "backup", "protect", "clean", "start", "ready"]


@pytest.mark.parametrize("failure", ["protect", "hash", "persist", "cleanup"])
def test_capture_finalize_failures_restart_and_are_classified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    manager, runner, _, app = _manager(tmp_path)
    original_validate_hash = manager._validate_hash
    original_cleanup = manager._cleanup_staging

    if failure == "protect":
        monkeypatch.setattr(manager, "_protect_backup", lambda *_args: (_ for _ in ()).throw(OSError("copy denied")))
    elif failure == "hash":
        calls = 0

        def fail_second_hash(path: Path, expected_hash: str, description: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("hash denied")
            original_validate_hash(path, expected_hash, description)

        monkeypatch.setattr(manager, "_validate_hash", fail_second_hash)
    elif failure == "persist":
        monkeypatch.setattr(
            manager._evidence_store,
            "save_checkpoint_manifest",
            lambda *_args: (_ for _ in ()).throw(OSError("persist denied")),
        )
    else:
        monkeypatch.setattr(
            manager,
            "_cleanup_staging",
            lambda staging, error: (
                original_cleanup(staging, error),
                (_ for _ in ()).throw(OSError("cleanup denied")),
            )[-1],
        )

    with pytest.raises(CheckpointInfrastructureError, match="denied"):
        manager.capture("baseline", (app,))

    assert any("Start-BCBenchServiceTier" in call for call in runner.calls)


def test_capture_reports_finalize_and_restart_failures_together(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager, runner, _, app = _manager(tmp_path)
    monkeypatch.setattr(manager, "_protect_backup", lambda *_args: (_ for _ in ()).throw(OSError("copy denied")))

    def fail_restart(script: str) -> subprocess.CompletedProcess[str]:
        result = runner(script)
        if "Start-BCBenchServiceTier" in script:
            return subprocess.CompletedProcess(args=["pwsh"], returncode=23, stdout="", stderr="restart denied")
        return result

    manager._powershell_runner = fail_restart

    with pytest.raises(CheckpointInfrastructureError, match=r"copy denied.*restart denied"):
        manager.capture("baseline", (app,))


@pytest.mark.parametrize(
    "seam",
    [
        "invoke",
        "validate_service",
        "parse_manifest",
        "validate_name",
        "validate_staging_backup",
        "validate_hash",
        "validate_container",
        "validate_apps",
        "protect_backup",
        "persist_manifest",
    ],
)
def test_capture_unexpected_post_staging_failures_cleanup_restart_and_propagate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seam: str,
) -> None:
    manager, runner, paths, app = _manager(tmp_path)

    if seam == "invoke":
        original = manager._invoke_json

        def fail_after_capture(operation: str, script: str):
            payload = original(operation, script)
            if operation == "capture":
                raise RuntimeError("unexpected capture failure")
            return payload

        monkeypatch.setattr(manager, "_invoke_json", fail_after_capture)
    elif seam == "persist_manifest":
        monkeypatch.setattr(
            manager._evidence_store,
            "save_checkpoint_manifest",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("unexpected capture failure")),
        )
    else:
        attribute = {
            "validate_service": "_validate_capture_service",
            "parse_manifest": "_parse_manifest",
            "validate_name": "_validate_capture_name",
            "validate_staging_backup": "_validated_staging_backup",
            "validate_hash": "_validate_hash",
            "validate_container": "_validate_container_identity",
            "validate_apps": "_validate_apps",
            "protect_backup": "_protect_backup",
        }[seam]
        original = getattr(manager, attribute)
        failed = False

        def fail_once(*args, **kwargs):
            nonlocal failed
            if not failed:
                failed = True
                raise RuntimeError("unexpected capture failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(manager, attribute, fail_once)

    with pytest.raises(RuntimeError, match="unexpected capture failure"):
        manager.capture("baseline", (app,))

    assert not any(paths.mounted_staging.iterdir())
    assert any("Start-BCBenchServiceTier" in call for call in runner.calls)


def test_capture_aggregates_unexpected_restart_and_cleanup_failures_with_causes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, runner, paths, app = _manager(tmp_path)
    original_cleanup = manager._cleanup_staging
    monkeypatch.setattr(manager, "_protect_backup", lambda *_args: (_ for _ in ()).throw(RuntimeError("primary exploded")))

    def cleanup_then_fail(staging_directory: Path, primary_error: CheckpointInfrastructureError | None) -> None:
        original_cleanup(staging_directory, primary_error)
        raise RuntimeError("cleanup exploded")

    def fail_restart(script: str) -> subprocess.CompletedProcess[str]:
        result = runner(script)
        if "Start-BCBenchServiceTier" in script:
            return subprocess.CompletedProcess(args=["pwsh"], returncode=29, stdout="", stderr="restart exploded")
        return result

    monkeypatch.setattr(manager, "_cleanup_staging", cleanup_then_fail)
    manager._powershell_runner = fail_restart

    with pytest.raises(CheckpointInfrastructureError, match=r"primary exploded.*restart exploded.*cleanup exploded") as caught:
        manager.capture("baseline", (app,))

    assert not any(paths.mounted_staging.iterdir())
    assert isinstance(caught.value.__cause__, ExceptionGroup)
    assert {str(error) for error in caught.value.__cause__.exceptions} >= {"primary exploded", "cleanup exploded"}


@pytest.mark.parametrize("seam", ["invoke", "protect"])
def test_capture_base_exception_cleans_staging_restarts_and_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seam: str,
) -> None:
    class SimulatedInterrupt(BaseException):
        pass

    manager, runner, paths, app = _manager(tmp_path)
    if seam == "invoke":
        original = manager._invoke_json

        def interrupt_after_capture(operation: str, script: str):
            payload = original(operation, script)
            if operation == "capture":
                raise SimulatedInterrupt
            return payload

        monkeypatch.setattr(manager, "_invoke_json", interrupt_after_capture)
    else:
        monkeypatch.setattr(manager, "_protect_backup", lambda *_args: (_ for _ in ()).throw(SimulatedInterrupt()))

    with pytest.raises(SimulatedInterrupt):
        manager.capture("baseline", (app,))

    assert not any(paths.mounted_staging.iterdir())
    assert any("Start-BCBenchServiceTier" in call for call in runner.calls)


def test_capture_invalid_manifest_still_restarts_owned_service(tmp_path: Path) -> None:
    manager, runner, _, app = _manager(tmp_path)
    runner.capture_payload = {
        "service": {
            "server_instance": "BC",
            "previous_process_id": 100,
            "state": "Stopped",
        }
    }

    with pytest.raises(CheckpointInfrastructureError, match="invalid manifest"):
        manager.capture("baseline", (app,))

    assert any("Start-BCBenchServiceTier" in call for call in runner.calls)


def test_capture_rejects_app_mismatch_and_cleans_staging(tmp_path: Path) -> None:
    manager, _, paths, _ = _manager(tmp_path)

    with pytest.raises(CheckpointInfrastructureError, match="application inventory"):
        manager.capture("baseline", (_app(content_hash="b" * 64),))

    assert not any(paths.mounted_staging.iterdir())
    assert not list(paths.checkpoints.rglob("*.bak"))


def test_capture_treats_null_and_available_hash_as_different_manifest_values(tmp_path: Path) -> None:
    manager, runner, _, _ = _manager(tmp_path)
    runner.app = _app(content_hash=None, package_id=None)

    with pytest.raises(CheckpointInfrastructureError, match="application inventory"):
        manager.capture("baseline", (_app(content_hash="a" * 64, package_id=None),))


def test_capture_rejects_container_identity_mismatch(tmp_path: Path) -> None:
    manager, runner, _, app = _manager(tmp_path)
    runner.identity = _identity(container_id="replacement-id")

    with pytest.raises(CheckpointInfrastructureError, match="container identity"):
        manager.capture("baseline", (app,))


@pytest.mark.parametrize(
    ("stdout", "returncode", "message"),
    [
        ("not-json", 0, "malformed JSON"),
        ("{}", 17, "exit code 17"),
    ],
)
def test_capture_reports_malformed_json_and_nonzero_exit(
    tmp_path: Path,
    stdout: str,
    returncode: int,
    message: str,
) -> None:
    manager, runner, _, app = _manager(tmp_path)
    runner.returncode = returncode
    runner.capture_payload = {}
    if stdout == "not-json":
        runner.capture_payload = None

        def malformed(_script: str) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=["pwsh"], returncode=0, stdout=stdout, stderr="")

        manager._powershell_runner = malformed

    with pytest.raises(CheckpointInfrastructureError, match=message):
        manager.capture("baseline", (app,))


def test_restore_stages_verified_copy_and_cleans_staging(tmp_path: Path) -> None:
    manager, runner, paths, app = _manager(tmp_path)
    manifest = manager.capture("baseline", (app,))

    manager.restore(manifest, (app,))

    assert len(runner.calls) == 3
    assert "Restore-BCBenchCheckpoint" in runner.calls[2]
    assert str(manifest.backup_path) not in runner.calls[2]
    assert not any(paths.mounted_staging.iterdir())


def test_restore_rejects_tampered_protected_checkpoint_before_powershell(tmp_path: Path) -> None:
    manager, runner, _, app = _manager(tmp_path)
    manifest = manager.capture("baseline", (app,))
    manifest.backup_path.write_bytes(b"tampered")

    with pytest.raises(CheckpointInfrastructureError, match="hash"):
        manager.restore(manifest, (app,))

    assert len(runner.calls) == 2


@pytest.mark.parametrize(
    ("returncode", "payload", "message"),
    [
        (19, {}, "exit code 19"),
        (0, None, "malformed JSON"),
    ],
)
def test_restore_reports_nonzero_and_malformed_json_and_cleans_staging(
    tmp_path: Path,
    returncode: int,
    payload: dict[str, object] | None,
    message: str,
) -> None:
    manager, runner, paths, app = _manager(tmp_path)
    manifest = manager.capture("baseline", (app,))

    def failed_restore(script: str) -> subprocess.CompletedProcess[str]:
        if "Restore-BCBenchCheckpoint" not in script:
            return runner(script)
        stdout = "not-json" if payload is None else json.dumps(payload)
        return subprocess.CompletedProcess(args=["pwsh"], returncode=returncode, stdout=stdout, stderr="restore failed")

    manager._powershell_runner = failed_restore

    with pytest.raises(CheckpointInfrastructureError, match=message):
        manager.restore(manifest, (app,))

    assert not any(paths.mounted_staging.iterdir())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("container", _identity(container_id="replacement"), "container identity"),
        ("apps", (_app(content_hash="b" * 64),), "application inventory"),
        ("service_restarted", False, "service"),
        ("database_online", False, "database"),
        ("company_endpoint_ready", False, "company"),
        ("test_discovery_ready", False, "test discovery"),
    ],
)
def test_restore_rejects_verification_mismatch(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    manager, runner, _, app = _manager(tmp_path)
    manifest = manager.capture("baseline", (app,))
    payload: dict[str, object] = {
        "container": manifest.container.to_dict(),
        "apps": [entry.to_dict() for entry in manifest.apps],
        "database_name": manifest.database_name,
        "database_folder": manifest.database_folder,
        "database_online": True,
        "service_restarted": True,
        "company_endpoint_ready": True,
        "test_discovery_ready": True,
    }
    payload[field] = value.to_dict() if isinstance(value, ContainerIdentity) else [entry.to_dict() for entry in value] if field == "apps" else value
    runner.restore_payload = payload

    with pytest.raises(CheckpointInfrastructureError, match=message):
        manager.restore(manifest, (app,))


def test_restore_rejects_checkpoint_outside_protected_root(tmp_path: Path) -> None:
    manager, runner, _, app = _manager(tmp_path)
    outside = tmp_path / "outside.bak"
    outside.write_bytes(b"backup")
    manifest = CheckpointManifest(
        name="baseline",
        backup_path=outside,
        sha256=sha256_file(outside),
        database_name="BC",
        database_folder="C:\\databases",
        container=_identity(),
        apps=(app,),
    )

    with pytest.raises(CheckpointInfrastructureError, match="protected checkpoint root"):
        manager.restore(manifest, (app,))

    assert runner.calls == []


def test_restore_failure_does_not_run_success_callback(tmp_path: Path) -> None:
    manager, runner, _, app = _manager(tmp_path)
    manifest = manager.capture("baseline", (app,))
    runner.returncode = 17
    phase_calls = 0

    def run_phase() -> None:
        nonlocal phase_calls
        phase_calls += 1

    with pytest.raises(CheckpointInfrastructureError):
        manager.restore(manifest, (app,), on_restored=run_phase)

    assert phase_calls == 0


@pytest.mark.parametrize("seam", ["copy", "staged_hash", "invoke", "validate"])
def test_restore_unexpected_post_staging_failures_cleanup_recover_and_skip_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seam: str,
) -> None:
    manager, runner, paths, app = _manager(tmp_path)
    manifest = manager.capture("baseline", (app,))
    runner.calls.clear()
    restored = False

    def on_restored() -> None:
        nonlocal restored
        restored = True

    if seam == "copy":
        monkeypatch.setattr(
            "bcbench.evaluate.bugfix_lifecycle.checkpoint.shutil.copyfile",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("unexpected restore failure")),
        )
    elif seam == "staged_hash":
        original = manager._validate_hash

        def fail_staged_hash(path: Path, expected_hash: str, description: str) -> None:
            if description == "staged checkpoint":
                raise RuntimeError("unexpected restore failure")
            original(path, expected_hash, description)

        monkeypatch.setattr(manager, "_validate_hash", fail_staged_hash)
    elif seam == "invoke":
        original = manager._invoke_json

        def fail_after_restore(operation: str, script: str):
            payload = original(operation, script)
            if operation == "restore":
                raise RuntimeError("unexpected restore failure")
            return payload

        monkeypatch.setattr(manager, "_invoke_json", fail_after_restore)
    else:
        monkeypatch.setattr(manager, "_validate_restore", lambda *_args: (_ for _ in ()).throw(RuntimeError("unexpected restore failure")))

    with pytest.raises(RuntimeError, match="unexpected restore failure"):
        manager.restore(manifest, (app,), on_restored=on_restored)

    assert not any(paths.mounted_staging.iterdir())
    assert restored is False
    if seam == "invoke":
        assert any("Start-BCBenchServiceTier" in call for call in runner.calls)


def test_restore_aggregates_unexpected_restart_and_cleanup_failures_and_skips_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, runner, paths, app = _manager(tmp_path)
    manifest = manager.capture("baseline", (app,))
    runner.calls.clear()
    original_invoke = manager._invoke_json
    original_cleanup = manager._cleanup_staging
    restored = False

    def fail_after_restore(operation: str, script: str):
        if operation == "restore restart":
            raise RuntimeError("restart exploded")
        payload = original_invoke(operation, script)
        if operation == "restore":
            raise RuntimeError("primary exploded")
        return payload

    def cleanup_then_fail(staging_directory: Path, primary_error: CheckpointInfrastructureError | None) -> None:
        original_cleanup(staging_directory, primary_error)
        raise RuntimeError("cleanup exploded")

    def on_restored() -> None:
        nonlocal restored
        restored = True

    monkeypatch.setattr(manager, "_invoke_json", fail_after_restore)
    monkeypatch.setattr(manager, "_cleanup_staging", cleanup_then_fail)

    with pytest.raises(CheckpointInfrastructureError, match=r"primary exploded.*restart exploded.*cleanup exploded") as caught:
        manager.restore(manifest, (app,), on_restored=on_restored)

    assert not any(paths.mounted_staging.iterdir())
    assert restored is False
    assert isinstance(caught.value.__cause__, ExceptionGroup)


def test_capture_cleanup_keyboard_interrupt_restarts_before_reraising(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, runner, paths, app = _manager(tmp_path)
    original_cleanup = manager._cleanup_staging

    def cleanup_then_interrupt(
        staging_directory: Path,
        primary_error: CheckpointInfrastructureError | None,
    ) -> None:
        original_cleanup(staging_directory, primary_error)
        raise KeyboardInterrupt("cleanup interrupted")

    monkeypatch.setattr(manager, "_cleanup_staging", cleanup_then_interrupt)

    with pytest.raises(KeyboardInterrupt, match="cleanup interrupted"):
        manager.capture("baseline", (app,))

    assert not any(paths.mounted_staging.iterdir())
    assert any("Start-BCBenchServiceTier" in call for call in runner.calls)


def test_restore_aggregates_primary_cleanup_interrupt_and_restart_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, runner, paths, app = _manager(tmp_path)
    manifest = manager.capture("baseline", (app,))
    runner.calls.clear()
    original_invoke = manager._invoke_json
    original_cleanup = manager._cleanup_staging
    operations: list[str] = []

    def fail_restore_and_restart(operation: str, script: str):
        operations.append(operation)
        if operation == "restore restart":
            raise RuntimeError("restart exploded")
        payload = original_invoke(operation, script)
        if operation == "restore":
            raise RuntimeError("primary exploded")
        return payload

    def cleanup_then_interrupt(
        staging_directory: Path,
        primary_error: CheckpointInfrastructureError | None,
    ) -> None:
        original_cleanup(staging_directory, primary_error)
        raise KeyboardInterrupt("cleanup interrupted")

    monkeypatch.setattr(manager, "_invoke_json", fail_restore_and_restart)
    monkeypatch.setattr(manager, "_cleanup_staging", cleanup_then_interrupt)

    with pytest.raises(BaseExceptionGroup) as caught:
        manager.restore(manifest, (app,))

    assert not any(paths.mounted_staging.iterdir())
    assert operations == ["restore", "restore restart"]
    diagnostics = str(caught.value)
    assert "primary exploded" in diagnostics
    assert "cleanup interrupted" in diagnostics
    assert "restart exploded" in diagnostics


def test_restore_base_exception_cleans_staging_recovers_and_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SimulatedInterrupt(BaseException):
        pass

    manager, runner, paths, app = _manager(tmp_path)
    manifest = manager.capture("baseline", (app,))
    runner.calls.clear()
    original = manager._invoke_json
    restored = False

    def interrupt_after_restore(operation: str, script: str):
        payload = original(operation, script)
        if operation == "restore":
            raise SimulatedInterrupt
        return payload

    def on_restored() -> None:
        nonlocal restored
        restored = True

    monkeypatch.setattr(manager, "_invoke_json", interrupt_after_restore)

    with pytest.raises(SimulatedInterrupt):
        manager.restore(manifest, (app,), on_restored=on_restored)

    assert not any(paths.mounted_staging.iterdir())
    assert any("Start-BCBenchServiceTier" in call for call in runner.calls)
    assert restored is False


def test_restore_filesystem_setup_failures_are_classified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager, _, _, app = _manager(tmp_path)
    manifest = manager.capture("baseline", (app,))
    monkeypatch.setattr("bcbench.evaluate.bugfix_lifecycle.checkpoint.tempfile.mkdtemp", lambda **_kwargs: (_ for _ in ()).throw(OSError("mkdtemp denied")))

    with pytest.raises(CheckpointInfrastructureError, match="mkdtemp denied"):
        manager.restore(manifest, (app,))


def test_cleanup_failure_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager, _, paths, app = _manager(tmp_path)
    original_rmtree = __import__("bcbench.evaluate.bugfix_lifecycle.checkpoint", fromlist=["shutil"]).shutil.rmtree

    def fail_staging_cleanup(path: Path) -> None:
        if Path(path).is_relative_to(paths.mounted_staging):
            raise OSError("cleanup denied")
        original_rmtree(path)

    monkeypatch.setattr("bcbench.evaluate.bugfix_lifecycle.checkpoint.shutil.rmtree", fail_staging_cleanup)

    with pytest.raises(CheckpointInfrastructureError, match="cleanup denied"):
        manager.capture("baseline", (app,))


@pytest.mark.e2e
def test_real_checkpoint_rehearsal() -> None:
    pytest.skip("requires an explicitly provisioned disposable BC checkpoint environment")
