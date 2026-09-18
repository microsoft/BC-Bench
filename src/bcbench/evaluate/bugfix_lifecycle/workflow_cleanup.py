import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from bcbench.agent.shared.contained_process import ContainedProcessInfrastructureError, ContainedProcessRequest, run_contained_process
from bcbench.evaluate.bugfix_lifecycle.path_safety import absolute_path, reject_reparse_components, require_disjoint
from bcbench.exceptions import CleanupInfrastructureError

_CLEANUP_ENVIRONMENT_KEYS = frozenset(
    {
        "ALLUSERSPROFILE",
        "APPDATA",
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "PSMODULEPATH",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
)


def _write_record(path: Path, payload: dict[str, object], *, exclusive: bool = False) -> None:
    reject_reparse_components(path, path.parent)
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(payload, stream)
        stream.flush()
        os.fsync(stream.fileno())


def _read_setup_identity(entry_root: Path, protected_root: Path, container_name: str) -> tuple[str, str]:
    setup = protected_root / "workflow-setup.json"
    reject_reparse_components(setup, protected_root)
    with setup.open(encoding="utf-8-sig") as stream:
        content = stream.read(1_048_577)
    if len(content) > 1_048_576:
        raise ValueError("Setup ownership record exceeds the size limit")
    state = json.loads(content)
    if (
        not isinstance(state, dict)
        or state.get("EntryRoot") != str(entry_root)
        or state.get("ProtectedRoot") != str(protected_root)
        or state.get("ContainerName") != container_name
        or not all(isinstance(state.get(key), str) and state[key].strip() for key in ("ContainerId", "ContainerInvocationId"))
    ):
        raise ValueError("Setup ownership does not match the allocated lifecycle")
    identity = state.get("AgentIdentity")
    if (
        not isinstance(identity, dict)
        or not isinstance(identity.get("Username"), str)
        or re.fullmatch(r"bcb-[a-f0-9]{7}-[a-f0-9]{6}", identity["Username"], re.IGNORECASE) is None
        or not isinstance(identity.get("Sid"), str)
        or re.fullmatch(r"S-\d+(?:-\d+)+", identity["Sid"]) is None
    ):
        raise ValueError("Setup has no valid restricted identity")
    return identity["Username"], identity["Sid"]


def _unverified_identity_security(entry_root: Path, protected_root: Path, container_name: str) -> dict[str, object]:
    evidence: dict[str, object] = {
        "status": "unverified",
        "ownership": "unverified",
        "local_identity_verified": False,
        "reason": "Cleanup did not verify identity disablement or removal. The account may remain enabled; manual containment is required.",
    }
    try:
        username, sid = _read_setup_identity(entry_root, protected_root, container_name)
        evidence.update(ownership="setup_record_validated", username=username, sid=sid)
    except (OSError, UnicodeError, ValueError) as error:
        evidence["ownership_error"] = f"Cannot establish the owned identity from setup ({type(error).__name__}); the supervisor did not target any account."
    return evidence


def _persist_cleanup_failure(
    entry_root: Path,
    protected_root: Path,
    container_name: str,
    payload: dict[str, object],
) -> None:
    payload["identity_security"] = _unverified_identity_security(entry_root, protected_root, container_name)
    protected_root.mkdir(exist_ok=True)
    _write_record(protected_root / "workflow-cleanup-worker.json", payload)
    _write_record(protected_root / "workflow-cleanup.json", payload)
    marker = protected_root / "quarantine.json"
    if not marker.exists():
        _write_record(marker, payload, exclusive=True)


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
        payload.update(status="failed", reason="interrupted cleanup worker; shutdown and identity security unverified")
        _persist_cleanup_failure(entry_root, protected_root, container_name, payload)
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
                env={name.upper(): value for name, value in os.environ.items() if name.upper() in _CLEANUP_ENVIRONMENT_KEYS},
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
        _persist_cleanup_failure(entry_root, protected_root, container_name, payload)
        raise CleanupInfrastructureError(reason) from error
