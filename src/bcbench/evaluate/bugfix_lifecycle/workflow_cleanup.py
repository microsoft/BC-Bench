import json
import os
import shutil
import subprocess
from pathlib import Path

from bcbench.agent.shared.contained_process import ContainedProcessInfrastructureError, ContainedProcessRequest, run_contained_process
from bcbench.evaluate.bugfix_lifecycle.path_safety import absolute_path, reject_reparse_components, require_disjoint
from bcbench.exceptions import CleanupInfrastructureError


def _write_record(path: Path, payload: dict[str, object], *, exclusive: bool = False) -> None:
    reject_reparse_components(path, path.parent)
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(payload, stream)
        stream.flush()
        os.fsync(stream.fileno())


def complete_workflow_cleanup(
    entry_root: Path,
    protected_root: Path,
    container_name: str,
    *,
    timeout_seconds: int = 180,
    worker_command: tuple[str, ...] | None = None,
) -> None:
    if timeout_seconds <= 0:
        raise ValueError("Cleanup deadline must be positive")
    entry_root = absolute_path(entry_root)
    protected_root = absolute_path(protected_root)
    require_disjoint(entry_root, protected_root, "entry root", "protected root")
    if entry_root == Path(entry_root.anchor) or protected_root == Path(protected_root.anchor):
        raise ValueError("Cleanup roots must not be filesystem roots")
    reject_reparse_components(protected_root, protected_root.parent)
    pending = protected_root.with_name(protected_root.name + ".cleanup-pending.quarantine.json")
    protected_root.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "status": "running",
        "worker_shutdown": "unverified",
        "entry_root": str(entry_root),
        "protected_root": str(protected_root),
        "container_name": container_name,
        "timeout_seconds": timeout_seconds,
    }
    try:
        _write_record(pending, payload, exclusive=True)
    except FileExistsError as error:
        protected_root.mkdir(exist_ok=True)
        marker = protected_root / "quarantine.json"
        if not marker.exists():
            _write_record(marker, {"status": "quarantined", "reason": "interrupted cleanup worker; shutdown unverified"}, exclusive=True)
        raise CleanupInfrastructureError("An interrupted cleanup attempt must be reviewed before retry") from error

    try:
        powershell = shutil.which("pwsh")
        if powershell is None:
            raise CleanupInfrastructureError("PowerShell is required for workflow cleanup")  # noqa: TRY301 - all worker failures must persist quarantine
        if worker_command is None and any(part.casefold() == "windowsapps" for part in Path(powershell).parts):
            raise CleanupInfrastructureError("Cleanup requires a non-packaged PowerShell executable")  # noqa: TRY301 - package activation can escape the owned job
        worker = Path(__file__).parents[4] / "scripts" / "Complete-BugFixLifecycle.ps1"
        command = worker_command or (powershell, "-NoProfile", "-NonInteractive", "-File", str(worker))
        result = run_contained_process(
            ContainedProcessRequest(
                command=(
                    *command,
                    "-EntryRoot",
                    str(entry_root),
                    "-ProtectedRoot",
                    str(protected_root),
                    "-ContainerName",
                    container_name,
                    "-Worker",
                ),
                cwd=Path(__file__).parents[4],
                env=dict(os.environ),
                timeout_seconds=timeout_seconds,
            )
        )
        payload["worker_shutdown"] = "verified"
        if result.returncode != 0:
            raise CleanupInfrastructureError("Cleanup worker failed; inspect protected workflow evidence")  # noqa: TRY301 - persist failed worker shutdown accounting
        payload["status"] = "success"
        _write_record(pending, payload)
        pending.unlink()
    except BaseException as error:
        if isinstance(error, subprocess.TimeoutExpired):
            # This exception is emitted only after the contained runner verifies an empty job.
            payload["worker_shutdown"] = "verified"
            reason = "Cleanup exceeded its total deadline"
        elif isinstance(error, ContainedProcessInfrastructureError):
            reason = "Cleanup containment shutdown is unverified"
        elif isinstance(error, CleanupInfrastructureError):
            reason = str(error)
        else:
            reason = "Cleanup failed or was interrupted"
        payload.update(status="failed", reason=reason)
        _write_record(pending, payload)
        protected_root.mkdir(exist_ok=True)
        _write_record(protected_root / "workflow-cleanup-worker.json", payload)
        _write_record(protected_root / "workflow-cleanup.json", payload)
        marker = protected_root / "quarantine.json"
        if not marker.exists():
            _write_record(marker, payload, exclusive=True)
        raise CleanupInfrastructureError(reason) from error
