import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from bcbench.agent.shared.contained_process import ContainedProcessRequest, run_contained_process
from bcbench.dataset import BugFixEntry
from bcbench.evaluate.bugfix_lifecycle.evidence import sha256_file
from bcbench.evaluate.bugfix_lifecycle.execution import WorkflowExecution
from bcbench.evaluate.bugfix_lifecycle.models import CheckpointManifest, ProjectPublication, ProvisionedLifecycleResources
from bcbench.evaluate.bugfix_lifecycle.path_safety import reject_reparse_components, require_strict_descendant
from bcbench.evaluate.bugfix_lifecycle.rehearsal import RehearsalFault, write_rehearsal_record
from bcbench.evaluate.bugfix_lifecycle.workflow_cleanup import _CLEANUP_ENVIRONMENT_KEYS
from bcbench.exceptions import CheckpointInfrastructureError
from bcbench.results.bugfix import BugFixPhaseStatus
from bcbench.types import ContainerConfig


def _read_evidence(path: Path, root: Path) -> dict[str, object]:
    reject_reparse_components(path, root)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("Expected an evidence object")
    return value


def require_rehearsal_evidence(
    resources: ProvisionedLifecycleResources,
    iterations: int,
    fault: RehearsalFault,
) -> None:
    try:
        _validate_rehearsal_evidence(resources, iterations, fault)
    except (OSError, TypeError, ValueError, KeyError) as error:
        raise CheckpointInfrastructureError(f"Rehearsal evidence validation failed ({type(error).__name__})") from error


def _validate_rehearsal_evidence(
    resources: ProvisionedLifecycleResources,
    iterations: int,
    fault: RehearsalFault,
) -> None:
    root = resources.paths.protected_root
    output = resources.paths.final_results / "rehearsal"
    checkpoints = _read_evidence(output / "checkpoints.json", root)
    official_value, rehearsal_value = checkpoints["official_s0"], checkpoints["rehearsal_only"]
    if not isinstance(official_value, dict) or not isinstance(rehearsal_value, dict):
        raise TypeError("Checkpoint evidence must contain two manifests")
    official = CheckpointManifest.from_dict(official_value)
    rehearsal = CheckpointManifest.from_dict(rehearsal_value)
    for manifest in (official, rehearsal):
        require_strict_descendant(manifest.backup_path, resources.paths.checkpoints, "backup", "protected checkpoints")
        reject_reparse_components(manifest.backup_path, root)
        if sha256_file(manifest.backup_path) != manifest.sha256:
            raise ValueError("Checkpoint hash changed after rehearsal")
    if (
        official.name != "baseline"
        or not rehearsal.name.startswith("rehearsal-")
        or official.backup_path == rehearsal.backup_path
        or official.container != rehearsal.container
        or official.apps != rehearsal.apps
        or official.container.container_id != resources.expected_container_id
    ):
        raise ValueError("Official and rehearsal checkpoint identities differ")
    clean = _read_evidence(output / "clean-s0.json", root)
    if clean.get("verified") is not True or clean.get("probe_absent") is not True or clean.get("checkpoint_sha256") != official.sha256:
        raise ValueError("Clean official S0 was not verified")
    count = iterations if fault in (RehearsalFault.NONE, RehearsalFault.CLEANUP_FAILURE) else 1
    records = sorted(output.glob("iteration-*.json"))
    if len(records) != count:
        raise ValueError("Wrong number of consecutive rehearsal records")
    expected_status = BugFixPhaseStatus.PASSED if fault in (RehearsalFault.NONE, RehearsalFault.CLEANUP_FAILURE) else BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    for index, path in enumerate(records, start=1):
        record = _read_evidence(path, root)
        if (
            record.get("iteration") != index
            or record.get("verified") is not True
            or record.get("status") != expected_status.value
            or record.get("fault") != fault.value
            or record.get("container_id") != resources.expected_container_id
            or record.get("official_s0_sha256") != official.sha256
            or record.get("rehearsal_sha256") != rehearsal.sha256
        ):
            raise ValueError("Incomplete or mismatched rehearsal iteration evidence")


def run_rehearsal_worker(
    resources: ProvisionedLifecycleResources,
    container: ContainerConfig,
    entry: BugFixEntry,
    *,
    iterations: int,
    fault: RehearsalFault = RehearsalFault.NONE,
    s0: CheckpointManifest | None = None,
    publication: ProjectPublication | None = None,
    checkpoint_path: Path | None = None,
) -> None:
    if type(iterations) is not int or not 1 <= iterations <= 100:
        raise ValueError("Rehearsal iterations must be between 1 and 100")
    powershell = shutil.which("pwsh")
    if powershell is None or "windowsapps" in (part.casefold() for part in Path(powershell).parts):
        raise CheckpointInfrastructureError("Rehearsal requires native PowerShell 7, not Store activation")
    if (s0 is None) != (publication is None):
        raise ValueError("Existing official S0 requires its trusted baseline publication")
    root = resources.paths.protected_root
    checkpoint_path = require_strict_descendant(
        checkpoint_path or resources.paths.checkpoints / "official-s0.json",
        resources.paths.checkpoints,
        "official manifest",
        "protected checkpoints",
    )
    reject_reparse_components(checkpoint_path, root)
    if checkpoint_path.exists():
        raise CheckpointInfrastructureError("Refusing to overwrite an existing official S0 manifest")
    request_path = root / "workflow-rehearsal-request.json"
    reject_reparse_components(request_path, root)
    if request_path.exists():
        raise CheckpointInfrastructureError("Rehearsal is already launched; no reset/retry is allowed")
    payload = {
        "resources": asdict(resources),
        "entry": entry.model_dump(mode="json"),
        "container": {"name": container.name, "company": container.company},
        "iterations": iterations,
        "fault": fault.value,
        "checkpoint_path": str(checkpoint_path),
        "s0": s0.to_dict() if s0 is not None else None,
        "publication": asdict(publication) if publication is not None else None,
    }
    # This handoff contains only nonsecret metadata. Credentials travel in the worker environment.
    write_rehearsal_record(request_path, json.loads(json.dumps(payload, default=str)))
    execution = WorkflowExecution(resources)
    execution.begin_rehearsal()
    record_path = root / "workflow-rehearsal.json"
    status = {"status": "running", "worker_shutdown": "unverified", "container_id": resources.expected_container_id, "invocation_id": resources.expected_container_invocation_id}
    write_rehearsal_record(record_path, status)
    credential_environment = {"BC_SERVER_USERNAME": container.username, "BC_SERVER_PASSWORD": container.password, "BC_COMPANY": container.company}
    previous = {name: os.environ.get(name) for name in credential_environment}
    try:
        os.environ.update(credential_environment)
        result = run_contained_process(
            ContainedProcessRequest(
                command=(sys.executable, "-m", "bcbench.commands.bugfix_rehearsal", "--worker", str(request_path)),
                cwd=resources.benchmark_root,
                env={name.upper(): value for name, value in os.environ.items() if name.upper() in _CLEANUP_ENVIRONMENT_KEYS},
                parent_environment_keys=tuple(credential_environment),
                timeout_seconds=min(21600, 3600 + iterations * 1200),
            )
        )
        status["worker_shutdown"] = "verified"
        if result.returncode:
            raise CheckpointInfrastructureError("Rehearsal worker failed; inspect protected rehearsal records")  # noqa: TRY301 - persist failure and verified shutdown together
        require_rehearsal_evidence(resources, iterations, fault)
        status["status"] = "success"
        write_rehearsal_record(record_path, status)
        execution.finish_rehearsal(resume_lifecycle=s0 is not None)
    except BaseException as error:
        if isinstance(error, subprocess.TimeoutExpired):
            status["worker_shutdown"] = "verified"
        status.update(status="failed", error_type=type(error).__name__)
        if not (root / "quarantine.json").exists():
            write_rehearsal_record(
                root / "quarantine.json",
                {
                    "status": "quarantined",
                    "reason": "rehearsal_failure_requires_review",
                    "container_id": resources.expected_container_id,
                    "invocation_id": resources.expected_container_invocation_id,
                },
            )
        raise
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        write_rehearsal_record(record_path, status)
