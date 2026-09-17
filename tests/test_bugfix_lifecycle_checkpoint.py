import json
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


def _app(*, content_hash: str = "a" * 64, name: str = "Library") -> AppInventoryEntry:
    return AppInventoryEntry(
        app_id="11111111-1111-1111-1111-111111111111",
        name=name,
        publisher="Microsoft",
        version="1.2.3.4",
        package_id="22222222-2222-2222-2222-222222222222",
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
        self.returncode = 0
        self.stderr = ""

    def __call__(self, script: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(script)
        if "Backup-BCBenchCheckpoint" in script:
            staging = self.paths.mounted_staging / "baseline-capture"
            staging.mkdir()
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
            }
        else:
            payload = self.restore_payload or {
                "container": self.identity.to_dict(),
                "apps": [self.app.to_dict()],
                "database_name": "BC",
                "database_folder": "C:\\databases",
                "database_online": True,
                "service_restarted": True,
                "company_endpoint_ready": True,
                "test_discovery_ready": True,
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
    )
    return manager, runner, paths, app


def test_checkpoint_models_are_immutable_and_json_paths_are_explicit(tmp_path: Path) -> None:
    backup = tmp_path / "checkpoint.bak"
    identity = _identity()
    manifest = CheckpointManifest(
        name="baseline",
        backup_path=backup,
        sha256="a" * 64,
        database_name="BC",
        database_folder=Path("C:\\databases"),
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


def test_capture_protects_backup_persists_manifest_and_removes_staging(tmp_path: Path) -> None:
    manager, runner, paths, app = _manager(tmp_path)

    manifest = manager.capture("baseline", (app,))

    assert manifest.backup_path.parent == paths.checkpoints / "baseline"
    assert manifest.backup_path.read_bytes() == b"verified database backup"
    assert manifest.sha256 == sha256_file(manifest.backup_path)
    assert not any(paths.mounted_staging.iterdir())
    persisted = json.loads((paths.evidence / "checkpoints" / "baseline.json").read_text(encoding="utf-8"))
    assert persisted == manifest.to_dict()
    assert len(runner.calls) == 1
    assert "Backup-BCBenchCheckpoint" in runner.calls[0]
    assert "invocation-id" in runner.calls[0]


def test_capture_rejects_app_mismatch_and_cleans_staging(tmp_path: Path) -> None:
    manager, _, paths, _ = _manager(tmp_path)

    with pytest.raises(CheckpointInfrastructureError, match="application inventory"):
        manager.capture("baseline", (_app(content_hash="b" * 64),))

    assert not any(paths.mounted_staging.iterdir())
    assert not list(paths.checkpoints.rglob("*.bak"))


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

    assert len(runner.calls) == 2
    assert "Restore-BCBenchCheckpoint" in runner.calls[1]
    assert str(manifest.backup_path) not in runner.calls[1]
    assert not any(paths.mounted_staging.iterdir())


def test_restore_rejects_tampered_protected_checkpoint_before_powershell(tmp_path: Path) -> None:
    manager, runner, _, app = _manager(tmp_path)
    manifest = manager.capture("baseline", (app,))
    manifest.backup_path.write_bytes(b"tampered")

    with pytest.raises(CheckpointInfrastructureError, match="hash"):
        manager.restore(manifest, (app,))

    assert len(runner.calls) == 1


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
        if "Backup-BCBenchCheckpoint" in script:
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
        "database_folder": str(manifest.database_folder),
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
        database_folder=Path("C:\\databases"),
        container=_identity(),
        apps=(app,),
    )

    with pytest.raises(CheckpointInfrastructureError, match="protected checkpoint root"):
        manager.restore(manifest, (app,))

    assert runner.calls == []


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
