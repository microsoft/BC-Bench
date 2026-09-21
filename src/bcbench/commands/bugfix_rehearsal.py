import argparse
import json
import os
import sys
from dataclasses import fields
from pathlib import Path

from bcbench.commands.bugfix_lifecycle import _parse_setup_ownership_envelope
from bcbench.dataset import BugFixEntry
from bcbench.evaluate.bugfix_lifecycle import CheckpointManager, EvidenceStore, ProductionBugFixLifecycle
from bcbench.evaluate.bugfix_lifecycle.models import (
    AppInventoryEntry,
    BugFixLifecyclePaths,
    CheckpointManifest,
    OwnedLifecycleRoot,
    ProjectPublication,
    ProvisionedLifecycleResources,
)
from bcbench.evaluate.bugfix_lifecycle.path_safety import reject_reparse_components, require_strict_descendant, validate_provisioned_lifecycle_resources
from bcbench.evaluate.bugfix_lifecycle.phases import classify_phase_error
from bcbench.evaluate.bugfix_lifecycle.rehearsal import RehearsalFault, run_checkpoint_rehearsal, select_rehearsal_app, write_rehearsal_record
from bcbench.evaluate.bugfix_lifecycle.rehearsal_adapter import PowerShellRehearsalAdapter, RehearsalExecutionGuard
from bcbench.evaluate.bugfix_lifecycle.rehearsal_execution import run_rehearsal_worker
from bcbench.exceptions import CleanupInfrastructureError
from bcbench.types import ContainerConfig


def _resources_from_payload(value: dict) -> ProvisionedLifecycleResources:
    value = dict(value)
    value["paths"] = BugFixLifecyclePaths(**{field.name: Path(value["paths"][field.name]) for field in fields(BugFixLifecyclePaths)})
    for key in ("benchmark_root", "staged_worker_path", "base_python", "python_base_prefix"):
        value[key] = Path(value[key])
    for key in ("cleanup_tool_roots", "acl_paths"):
        value[key] = tuple(Path(path) for path in value[key])
    value["compiler_helper_roots"] = tuple(OwnedLifecycleRoot(Path(item["path"]), item["ownership_token"]) for item in value["compiler_helper_roots"])
    return validate_provisioned_lifecycle_resources(ProvisionedLifecycleResources(**value))


def _worker(path: Path) -> None:
    reject_reparse_components(path, path.parent)
    payload = json.loads(path.read_text(encoding="utf-8"))
    resources = _resources_from_payload(payload["resources"])
    if path != resources.paths.protected_root / "workflow-rehearsal-request.json":
        raise ValueError("Rehearsal handoff is not in its owned protected root")
    container = ContainerConfig(**payload["container"], username=os.environ["BC_SERVER_USERNAME"], password=os.environ["BC_SERVER_PASSWORD"])
    entry = BugFixEntry.model_validate(payload["entry"])
    if entry.instance_id != resources.instance_id or container.name != resources.container_name or container.company != os.environ["BC_COMPANY"]:
        raise ValueError("Rehearsal handoff ownership or company mismatch")
    checkpoint_path = require_strict_descendant(Path(payload["checkpoint_path"]), resources.paths.checkpoints, "checkpoint manifest", "protected checkpoints")
    if checkpoint_path.exists():
        raise ValueError("Official checkpoint manifest already exists")
    execution_guard = RehearsalExecutionGuard()
    if payload["s0"] is None:
        lifecycle = ProductionBugFixLifecycle.from_resources(
            resources,
            container,
            entry,
            powershell_runner=execution_guard.run,
            baseline_operation_guard=execution_guard.operation,
        )
        with execution_guard.operation():
            _, s0 = lifecycle.prepare_baseline(resources, entry)
        publication = lifecycle.baseline_publication
        if publication is None:
            raise ValueError("Official baseline publication has no package provenance")
    else:
        s0 = CheckpointManifest.from_dict(payload["s0"])
        data = payload["publication"]
        publication = ProjectPublication(
            tuple(data["project_paths"]),
            tuple(Path(item) for item in data["package_paths"]),
            tuple(AppInventoryEntry.from_dict(item) for item in data["apps"]),
        )
    if s0.name != "baseline" or s0.container.container_id != resources.expected_container_id:
        raise ValueError("Rehearsal requires the clean official baseline of this owned container")
    write_rehearsal_record(checkpoint_path, s0.to_dict())
    for package in publication.package_paths:
        require_strict_descendant(package, resources.paths.final_results, "baseline package", "protected final results")
        reject_reparse_components(package, resources.paths.protected_root)
    app = select_rehearsal_app(publication, s0.apps, entry.project_paths)
    output = resources.paths.final_results / "rehearsal"
    adapter = PowerShellRehearsalAdapter(resources, container, s0, output, tuple(entry.pass_to_pass), execution_guard=execution_guard)
    checkpoint = CheckpointManager(
        resources.paths,
        EvidenceStore(resources.paths),
        adapter.run,
        container_name=resources.container_name,
        container_id=resources.expected_container_id,
        invocation_id=resources.expected_container_invocation_id,
        expected_company=container.company,
    )
    run_checkpoint_rehearsal(checkpoint, s0, adapter, app, output, iterations=payload["iterations"], fault=RehearsalFault(payload["fault"]))


def _from_environment() -> tuple[ProvisionedLifecycleResources, ContainerConfig, BugFixEntry]:
    prefix = "BCBENCH_LIFECYCLE_"
    env = os.environ
    root = Path(env[prefix + "PROTECTED_ROOT"])
    reject_reparse_components(root / "workflow-setup.json", root)
    setup = json.loads((root / "workflow-setup.json").read_text(encoding="utf-8-sig"))
    resources = _parse_setup_ownership_envelope(
        entry_id=setup["InstanceId"],
        entry_root=Path(env[prefix + "ENTRY_ROOT"]),
        protected_root=root,
        container_name=env["BC_CONTAINER_NAME"],
        expected_container_id=env[prefix + "EXPECTED_CONTAINER_ID"],
        expected_invocation_id=env[prefix + "EXPECTED_INVOCATION_ID"],
        agent_os_username=env[prefix + "AGENT_OS_USERNAME"],
        agent_bc_username=env[prefix + "AGENT_BC_USERNAME"],
        agent_os_sid=env[prefix + "AGENT_OS_SID"],
        staged_worker_path=Path(env[prefix + "STAGED_WORKER_PATH"]),
        base_python=Path(env[prefix + "BASE_PYTHON"]),
        python_base_prefix=Path(env[prefix + "PYTHON_BASE_PREFIX"]),
        acl_paths_json=env.get(prefix + "ACL_PATHS_JSON"),
        cleanup_tool_roots_json=env.get(prefix + "CLEANUP_TOOL_ROOTS_JSON"),
        owned_compiler_helper_roots=[Path(item) for item in env.get(prefix + "OWNED_COMPILER_HELPER_ROOTS", "").split(os.pathsep) if item],
    )
    resources = validate_provisioned_lifecycle_resources(resources)
    if (
        setup["ContainerId"] != resources.expected_container_id
        or setup["ContainerInvocationId"] != resources.expected_container_invocation_id
        or setup["ContainerName"] != resources.container_name
        or setup["EntryRoot"] != str(resources.paths.entry_root)
        or setup["ProtectedRoot"] != str(resources.paths.protected_root)
        or setup["AgentIdentity"]["Username"] != resources.agent_os_username
        or setup["AgentIdentity"]["Sid"] != resources.agent_os_sid
        or setup["AgentBcIdentity"]["Username"] != resources.agent_bc_username
        or setup["Status"] != "ready"
    ):
        raise ValueError("Rehearsal environment does not match durable setup ownership")
    container = ContainerConfig(
        name=resources.container_name,
        username=env["BC_SERVER_USERNAME"],
        password=env["BC_SERVER_PASSWORD"],
        company=env["BC_COMPANY"],
        server_url=env.get("BC_SERVER_URL", ""),
        server_instance=env.get("BC_SERVER_INSTANCE", ""),
    )
    dataset = require_strict_descendant(Path(env[prefix + "DATASET_PATH"]), resources.benchmark_root, "setup dataset", "benchmark checkout")
    entry = BugFixEntry.load(dataset, entry_id=resources.instance_id)[0]
    return resources, container, entry


def verify_cleanup_fault(root: Path) -> None:
    payloads = []
    for name in ("workflow-setup.json", "workflow-cleanup-worker.json", "quarantine.json"):
        reject_reparse_components(root / name, root)
        payloads.append(json.loads((root / name).read_text(encoding="utf-8-sig")))
    setup, worker, quarantine = payloads
    errors = quarantine.get("cleanup_errors")
    if (
        worker.get("worker_shutdown") != "verified"
        or quarantine.get("expected_container_id") != setup["ContainerId"]
        or quarantine.get("expected_invocation_id") != setup["ContainerInvocationId"]
        or not isinstance(errors, list)
        or len(errors) != 1
        or not isinstance(errors[0], str)
        or "still exists after removal." not in errors[0]
    ):
        raise CleanupInfrastructureError("CleanupFailure did not produce the exact owned-container absence-check failure")
    error = CleanupInfrastructureError(errors[0])
    status = classify_phase_error(error)
    if status is None:
        raise error
    write_rehearsal_record(
        root / "workflow-rehearsal-cleanup-fault.json",
        {
            "verified": True,
            "status": status.value,
            "fault": RehearsalFault.CLEANUP_FAILURE.value,
            "container_id": setup["ContainerId"],
            "invocation_id": setup["ContainerInvocationId"],
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--verify-cleanup-fault", type=Path)
    parser.add_argument("--container-name")
    parser.add_argument("--checkpoint-path", type=Path)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--fault", choices=list(RehearsalFault), default=RehearsalFault.NONE)
    args = parser.parse_args()
    if args.verify_cleanup_fault:
        verify_cleanup_fault(args.verify_cleanup_fault)
        return 0
    if args.worker:
        try:
            _worker(args.worker)
        except BaseException as error:  # noqa: BLE001 - fail the worker and persist nonsecret cancellation/error evidence
            # Raw tracebacks/tool stdout can carry credentials; the durable status records are nonsecret.
            write_rehearsal_record(args.worker.parent / "workflow-rehearsal-worker.json", {"status": "failed", "error_type": type(error).__name__})
            return 1
        return 0
    resources, container, entry = _from_environment()
    if args.container_name != resources.container_name:
        raise ValueError("Requested container differs from setup ownership")
    run_rehearsal_worker(resources, container, entry, iterations=args.iterations, fault=RehearsalFault(args.fault), checkpoint_path=args.checkpoint_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
