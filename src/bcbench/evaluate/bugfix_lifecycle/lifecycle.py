from __future__ import annotations

import json
import os
import subprocess
import tempfile
import traceback
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from bcbench.agent.shared.contained_process import AgentExecutionPolicy, ContainedProcessInfrastructureError
from bcbench.dataset import BugFixEntry, TestEntry
from bcbench.evaluate import bugfix_output
from bcbench.evaluate.bugfix_lifecycle.checkpoint import CheckpointManager, PowerShellResult, PowerShellRunner
from bcbench.evaluate.bugfix_lifecycle.evidence import EvidenceStore, sha256_file, sha256_text
from bcbench.evaluate.bugfix_lifecycle.execution import WorkflowExecution
from bcbench.evaluate.bugfix_lifecycle.models import (
    AppInventoryEntry,
    BugFixLifecycleRequest,
    CheckpointManifest,
    ContainerIdentity,
    ProjectPublication,
    ProvisionedLifecycleResources,
    SubmissionAnalysis,
    TrustedSource,
)
from bcbench.evaluate.bugfix_lifecycle.path_safety import (
    ENTRY_MANAGED_PATH_NAMES,
    absolute_path,
    reject_reparse_components,
    require_strict_descendant,
    validate_agent_plugin_root,
    validate_cleanup_acl_paths,
    validate_owned_lifecycle_roots,
)
from bcbench.evaluate.bugfix_lifecycle.phases import (
    BugFixPhaseRunner,
    DefaultProjectPublisher,
    make_invalid_submission_phase,
    make_not_run_phase,
)
from bcbench.evaluate.bugfix_lifecycle.workspace import TrustedWorkspaceBuilder
from bcbench.evaluate.bugfix_output import GeneratedBugFixOutput
from bcbench.exceptions import (
    AgentError,
    AgentTimeoutError,
    BugFixLifecycleInfrastructureError,
    CleanupInfrastructureError,
    EmptyDiffError,
    GeneratedOutputError,
    GeneratedSubmissionError,
    NoTestsExtractedError,
    PhaseExecutionInfrastructureError,
    ProjectDiscoveryError,
    TestExtractionError,
)
from bcbench.logger import get_logger
from bcbench.operations import (
    commit_changes,
    copy_problem_statement_folder,
    set_runtime_version,
    setup_repo_prebuild,
    stage_and_get_complete_diff,
)
from bcbench.operations.filesystem_operations import remove_tree
from bcbench.operations.git_operations import resolve_trusted_commit
from bcbench.operations.project_operations import find_project_path, is_test_project, order_project_paths
from bcbench.results.bugfix import BugFixMetricName, BugFixPhaseResult, BugFixPhaseStatus, BugFixResult
from bcbench.types import AgentMetrics, EvaluationContext, ExperimentConfiguration

logger = get_logger(__name__)

BaselinePublisher = Callable[[Path, tuple[str, ...]], object]
SubmissionAnalyzer = Callable[[Path, str, str, Iterable[str]], SubmissionAnalysis]
PhaseRunnerFactory = Callable[[TrustedSource], BugFixPhaseRunner]


class ProductionAgentRunner(Protocol):
    def __call__(
        self,
        context: EvaluationContext[BugFixEntry],
        execution_policy: AgentExecutionPolicy,
        /,
    ) -> tuple[AgentMetrics | None, ExperimentConfiguration | None]: ...


class LifecycleOwnershipApi(Protocol):
    def get_container_identity(self) -> ContainerIdentity: ...

    def read_app_inventory(self) -> Sequence[AppInventoryEntry]: ...

    def close_contained_group(self) -> None: ...

    def stop_agent_sessions(self) -> None: ...

    def verify_container_ownership(self) -> None: ...

    def stop_evaluator_processes(self) -> None: ...

    def remove_bc_user(self) -> None: ...

    def remove_container_and_verify(self) -> None: ...

    def remove_acl(self) -> None: ...

    def remove_local_identity(self) -> None: ...

    def remove_roots(self) -> None: ...

    def disable_local_identity(self) -> None: ...


class _CleanupOwner(Enum):
    CLI = "cli"
    LIFECYCLE = "lifecycle"
    RELEASED = "released"


@dataclass
class CleanupLease:
    resources: ProvisionedLifecycleResources
    _owner: _CleanupOwner = field(default=_CleanupOwner.CLI, init=False, repr=False)

    @classmethod
    def for_cli(cls, resources: ProvisionedLifecycleResources) -> CleanupLease:
        return cls(resources)

    @classmethod
    def for_lifecycle(cls, resources: ProvisionedLifecycleResources) -> CleanupLease:
        lease = cls(resources)
        lease.transfer_to_lifecycle()
        return lease

    @property
    def is_lifecycle_owner(self) -> bool:
        return self._owner is _CleanupOwner.LIFECYCLE

    def replace_resources(self, resources: ProvisionedLifecycleResources) -> None:
        if self._owner is not _CleanupOwner.CLI:
            raise RuntimeError("Cleanup resources can only be replaced by the CLI owner")
        self.resources = resources

    def transfer_to_lifecycle(self) -> None:
        if self._owner is not _CleanupOwner.CLI:
            raise RuntimeError("Cleanup lease is not owned by the CLI")
        self._owner = _CleanupOwner.LIFECYCLE

    def cleanup_as_cli(
        self,
        cleanup: Callable[[], CleanupInfrastructureError | None],
    ) -> CleanupInfrastructureError | None:
        if self._owner is not _CleanupOwner.CLI:
            return None
        self._owner = _CleanupOwner.RELEASED
        return cleanup()

    def cleanup_as_lifecycle(
        self,
        cleanup: Callable[[], CleanupInfrastructureError | None],
    ) -> CleanupInfrastructureError | None:
        if self._owner is _CleanupOwner.RELEASED:
            raise RuntimeError("Cleanup lease was already released")
        if self._owner is not _CleanupOwner.LIFECYCLE:
            raise RuntimeError("Cleanup lease is not owned by the lifecycle")
        self._owner = _CleanupOwner.RELEASED
        return cleanup()


@dataclass(frozen=True)
class RawSetupCleanup:
    instance_id: str
    container_name: str
    expected_container_id: str
    expected_invocation_id: str
    agent_os_username: str
    agent_bc_username: str
    agent_os_sid: str
    entry_root: Path
    protected_root: Path
    staged_worker_path: Path
    base_python: Path
    python_base_prefix: Path
    acl_paths_json: str | None
    cleanup_tool_roots_json: str | None
    owned_compiler_helper_roots: tuple[Path, ...]

    def run(self, error: BaseException) -> CleanupInfrastructureError | None:
        payload = {
            "status": "quarantined",
            "reason": "ownership_envelope_parse_failure",
            "instance_id": self.instance_id,
            "container_name": self.container_name,
            "expected_container_id": self.expected_container_id,
            "expected_invocation_id": self.expected_invocation_id,
            "agent_os_username": self.agent_os_username,
            "agent_bc_username": self.agent_bc_username,
            "agent_os_sid": self.agent_os_sid,
            "entry_root": str(self.entry_root),
            "protected_root": str(self.protected_root),
            "staged_worker_path": str(self.staged_worker_path),
            "base_python": str(self.base_python),
            "python_base_prefix": str(self.python_base_prefix),
            "acl_paths_json": self.acl_paths_json,
            "cleanup_tool_roots_json": self.cleanup_tool_roots_json,
            "owned_compiler_helper_roots": [str(path) for path in self.owned_compiler_helper_roots],
            "original_error": str(error),
            "created_at_utc": datetime.now(UTC).isoformat(),
        }
        try:
            protected_root = _prepare_raw_quarantine_root(self.protected_root)
            _atomic_json(protected_root / "quarantine.json", payload)
        except Exception as quarantine_error:  # noqa: BLE001 - malformed setup must surface quarantine failure
            return CleanupInfrastructureError(f"Ownership envelope parsing failed and quarantine persistence failed: {quarantine_error}")
        return None


def _prepare_raw_quarantine_root(path: Path) -> Path:
    protected_root = absolute_path(path)
    if protected_root == Path(protected_root.anchor):
        raise ValueError("protected_root cannot be a filesystem root")
    reject_reparse_components(protected_root, protected_root)
    if protected_root.exists() and (not protected_root.is_dir() or protected_root.is_symlink()):
        raise ValueError(f"protected_root must be a directory: {protected_root}")
    protected_root.mkdir(parents=True, exist_ok=True)
    reject_reparse_components(protected_root, protected_root)
    return protected_root


@dataclass(frozen=True)
class LifecycleCleanup:
    resources: ProvisionedLifecycleResources
    ownership_api: LifecycleOwnershipApi
    stop_agent_clients: Callable[[], None] | None = None

    @classmethod
    def from_resources(
        cls,
        resources: ProvisionedLifecycleResources,
        *,
        powershell_runner: PowerShellRunner | None = None,
    ) -> LifecycleCleanup:
        ownership = PowerShellLifecycleOwnershipApi(
            resources,
            None,
            powershell_runner or _default_cleanup_powershell_runner(),
        )
        return cls(resources, ownership)

    def run(self) -> CleanupInfrastructureError | None:
        errors: list[str] = []
        completed_operations: list[str] = []
        container_absent = False
        identity_secured = False
        clients_stopped = True
        if self.stop_agent_clients is not None:
            try:
                self.stop_agent_clients()
            except Exception as error:  # noqa: BLE001 - continue securing identities/container and persist quarantine
                clients_stopped = False
                errors.append(f"agent client shutdown: {error}")
            else:
                completed_operations.append("agent_clients_stopped")
        try:
            WorkflowExecution(self.resources).require_shutdown()
            self.ownership_api.verify_container_ownership()
        except Exception as error:  # noqa: BLE001 - cleanup aggregates every ownership failure
            errors.append(f"container ownership verification: {error}")
        else:
            completed_operations.append("container_ownership_verified")
            for name, operation in (
                ("evaluator process stop", self.ownership_api.stop_evaluator_processes),
                ("BC user removal", self.ownership_api.remove_bc_user),
                ("container removal", self.ownership_api.remove_container_and_verify),
            ):
                try:
                    operation()
                except Exception as error:  # noqa: BLE001 - cleanup must continue to quarantine
                    errors.append(f"{name}: {error}")
                    break
                completed_operations.append(name.replace(" ", "_"))
            else:
                container_absent = True

        if container_absent and clients_stopped:
            for name, operation in (
                ("owned root removal", self.ownership_api.remove_roots),
                ("ACL removal", self.ownership_api.remove_acl),
                ("local identity removal", self.ownership_api.remove_local_identity),
            ):
                try:
                    operation()
                except Exception as error:  # noqa: BLE001 - cleanup must continue to quarantine
                    errors.append(f"{name}: {error}")
                    break
                completed_operations.append(name.replace(" ", "_"))
                if name == "local identity removal":
                    identity_secured = True

        if errors and not identity_secured:
            try:
                self.ownership_api.disable_local_identity()
            except Exception as error:  # noqa: BLE001 - quarantine records disablement failure
                errors.append(f"local identity disablement/verification: {error}")
            else:
                completed_operations.append("local_identity_disabled")

        cleanup_payload = {
            "status": "failure" if errors else "success",
            "instance_id": self.resources.instance_id,
            "container_id": self.resources.expected_container_id,
            "container_invocation_id": self.resources.expected_container_invocation_id,
            "completed_operations": completed_operations,
            "cleanup_errors": errors,
        }
        try:
            self.resources.paths.final_results.mkdir(parents=True, exist_ok=True)
            reject_reparse_components(
                self.resources.paths.final_results,
                self.resources.paths.protected_root,
            )
            _atomic_json(
                self.resources.paths.final_results / "cleanup.json",
                cleanup_payload,
            )
        except Exception as error:  # noqa: BLE001 - quarantine must capture cleanup record failure
            errors.append(f"cleanup record persistence: {error}")

        if not errors:
            return None

        quarantine_payload = {
            **cleanup_payload,
            "status": "quarantined",
            "cleanup_errors": errors,
            "entry_root": str(self.resources.paths.entry_root),
            "protected_root": str(self.resources.paths.protected_root),
            "local_username": self.resources.agent_os_username,
            "local_sid": self.resources.agent_os_sid,
        }
        try:
            self.resources.paths.protected_root.mkdir(parents=True, exist_ok=True)
            reject_reparse_components(
                self.resources.paths.protected_root,
                self.resources.paths.protected_root,
            )
            _atomic_json(
                self.resources.paths.protected_root / "quarantine.json",
                quarantine_payload,
            )
        except Exception as error:  # noqa: BLE001 - cleanup reports quarantine failure too
            errors.append(f"quarantine persistence: {error}")
        return CleanupInfrastructureError("; ".join(errors))


def analyze_bugfix_submission(
    repo_path: Path,
    generated_patch: str,
    trusted_commit: str,
    allowed_app_projects: Iterable[str],
) -> SubmissionAnalysis:
    try:
        submission = bugfix_output.analyze_generated_bugfix_output(
            repo_path,
            generated_patch,
            trusted_commit,
            allowed_app_projects,
        )
    except (GeneratedOutputError, GeneratedSubmissionError):
        return _analyze_submission_sides(
            repo_path,
            generated_patch,
            trusted_commit,
            allowed_app_projects,
        )
    return SubmissionAnalysis(submission=submission)


def _analyze_submission_sides(
    repo_path: Path,
    generated_patch: str,
    trusted_commit: str,
    allowed_app_projects: Iterable[str],
) -> SubmissionAnalysis:
    resolved_trusted_commit = resolve_trusted_commit(repo_path, trusted_commit)
    if not generated_patch.strip():
        return _globally_invalid_analysis(generated_patch, "Generated patch is blank.")

    try:
        parsed_files = bugfix_output._parse_patch_files(generated_patch)
    except (GeneratedOutputError, GeneratedSubmissionError) as error:
        return _globally_invalid_analysis(generated_patch, str(error))

    allowed_projects = {bugfix_output._canonical_project_path(repo_path, project_path) for project_path in allowed_app_projects}
    fix_files = []
    test_files = []
    app_projects: list[str] = []
    test_projects: list[str] = []
    fix_errors: list[str] = []
    test_errors: list[str] = []

    for parsed_file in parsed_files:
        changed_paths = bugfix_output._changed_paths(parsed_file.paths)
        try:
            project_paths = tuple(find_project_path(repo_path, path) for path in changed_paths)
        except ProjectDiscoveryError as error:
            return _globally_invalid_analysis(generated_patch, str(error))
        classifications = {is_test_project(project_path) for project_path in project_paths}
        if len(classifications) != 1:
            return _globally_invalid_analysis(
                generated_patch,
                f"Cannot safely split rename between product and test projects: {changed_paths[0]} -> {changed_paths[1]}.",
            )

        is_test = classifications == {True}
        target_errors = test_errors if is_test else fix_errors
        target_files = test_files if is_test else fix_files
        target_projects = test_projects if is_test else app_projects
        target_files.append(parsed_file)
        target_projects.extend(project_paths)

        try:
            _validate_parsed_file(
                repo_path,
                parsed_file,
                changed_paths,
                project_paths,
                is_test=is_test,
                allowed_projects=allowed_projects,
            )
        except (GeneratedOutputError, GeneratedSubmissionError) as error:
            target_errors.append(str(error))

    fix_patch = "".join(parsed.original_patch for parsed in fix_files)
    test_patch = "".join(parsed.original_patch for parsed in test_files)
    if not fix_patch:
        fix_errors.append("Agent produced tests but no product-code fix.")

    tests: tuple[TestEntry, ...] = ()
    if not test_patch:
        test_errors.append("No tests extracted from the generated patch.")
    elif not test_errors:
        try:
            tests = _analyze_generated_tests(
                repo_path,
                resolved_trusted_commit,
                test_files,
            )
        except (
            GeneratedOutputError,
            GeneratedSubmissionError,
            NoTestsExtractedError,
            TestExtractionError,
            ValueError,
        ) as error:
            test_errors.append(str(error))

    submission = GeneratedBugFixOutput(
        full_patch=generated_patch,
        fix_patch=fix_patch,
        test_patch=test_patch,
        app_projects=tuple(order_project_paths((), app_projects)),
        test_projects=tuple(order_project_paths((), test_projects)),
        tests=tests,
    )
    return SubmissionAnalysis(
        submission=submission,
        fix_error=_joined_errors(fix_errors),
        test_error=_joined_errors(test_errors),
    )


def _validate_parsed_file(
    repo_path: Path,
    parsed_file: bugfix_output._ParsedPatchFile,
    changed_paths: tuple[str, ...],
    project_paths: tuple[str, ...],
    *,
    is_test: bool,
    allowed_projects: set[str],
) -> None:
    bugfix_output._validate_al_paths(changed_paths)
    patched_file = parsed_file.patched_file
    if not patched_file and not bugfix_output._is_complete_rename(patched_file):
        raise GeneratedOutputError(f"Malformed generated patch: {patched_file.path} has no hunks.")
    if is_test:
        bugfix_output._validate_test_change(patched_file, changed_paths)
        bugfix_output._validate_no_added_conditional_compilation_directives(
            patched_file,
            changed_paths,
        )
        return
    for project_path in project_paths:
        if bugfix_output._canonical_project_path(repo_path, project_path) not in allowed_projects:
            raise GeneratedSubmissionError(f"Product project is not allowed: {project_path}")


def _analyze_generated_tests(
    repo_path: Path,
    trusted_commit: str,
    test_files: Sequence[bugfix_output._ParsedPatchFile],
) -> tuple[TestEntry, ...]:
    occurrences = bugfix_output._find_generated_test_occurrences(
        repo_path,
        trusted_commit,
        test_files,
    )
    if len(occurrences) != 1:
        raise GeneratedSubmissionError(f"Expected exactly one new test procedure, found {len(occurrences)}.")
    return tuple(bugfix_output.normalize_test_occurrences(occurrences))


def _globally_invalid_analysis(patch: str, error: str) -> SubmissionAnalysis:
    submission = GeneratedBugFixOutput(
        full_patch=patch,
        fix_patch="",
        test_patch="",
        app_projects=(),
        test_projects=(),
        tests=(),
    )
    return SubmissionAnalysis(submission=submission, fix_error=error, test_error=error)


def _joined_errors(errors: Sequence[str]) -> str | None:
    unique = tuple(dict.fromkeys(error for error in errors if error))
    return "; ".join(unique) if unique else None


class ProductionBugFixLifecycle:
    def __init__(
        self,
        *,
        evidence_store: EvidenceStore,
        workspace_builder: TrustedWorkspaceBuilder,
        checkpoint_manager: CheckpointManager,
        phase_runner_factory: PhaseRunnerFactory,
        ownership_api: LifecycleOwnershipApi,
        baseline_publisher: BaselinePublisher,
        analyzer: SubmissionAnalyzer = analyze_bugfix_submission,
        setup_repo: Callable[[BugFixEntry, Path], None] = setup_repo_prebuild,
        copy_problem: Callable[[BugFixEntry, Path], None] = copy_problem_statement_folder,
        set_runtime: Callable[[Path, list[str]], None] = set_runtime_version,
        commit_changes: Callable[..., None] = commit_changes,
        freeze_submission: Callable[[Path, str], str] = stage_and_get_complete_diff,
    ) -> None:
        self._evidence_store = evidence_store
        self._workspace_builder = workspace_builder
        self._checkpoint_manager = checkpoint_manager
        self._phase_runner_factory = phase_runner_factory
        self._ownership_api = ownership_api
        self._baseline_publisher = baseline_publisher
        self._analyzer = analyzer
        self._setup_repo = setup_repo
        self._copy_problem = copy_problem
        self._set_runtime = set_runtime
        self._commit_changes = commit_changes
        self._freeze_submission = freeze_submission

    @classmethod
    def from_request(
        cls,
        request: BugFixLifecycleRequest,
        *,
        powershell_runner: PowerShellRunner | None = None,
    ) -> ProductionBugFixLifecycle:
        evidence = EvidenceStore(request.paths)
        workspace = TrustedWorkspaceBuilder(request.paths)
        runner = powershell_runner or _default_powershell_runner(request)
        ownership = PowerShellLifecycleOwnershipApi(
            request.provisioned_resources,
            evidence,
            runner,
        )
        checkpoint = CheckpointManager(
            request.paths,
            evidence,
            runner,
            container_name=request.evaluator_container.name,
            container_id=request.expected_container_id,
            invocation_id=request.expected_container_invocation_id,
            expected_company=request.evaluator_container.company,
        )
        publisher = DefaultProjectPublisher(
            request.evaluator_container,
            request.context.entry.environment_setup_version,
        )

        def baseline_publisher(
            repo_path: Path,
            project_paths: tuple[str, ...],
        ) -> ProjectPublication:
            evidence_directory = request.paths.evidence / "baseline-publication"
            publication = publisher.build_and_publish_with_evidence(
                repo_path,
                project_paths,
                evidence_directory,
            )
            for path in publication.evidence_paths:
                evidence.protect_artifact(path, "baseline-publication-evidence")
            for path in publication.package_paths:
                evidence.protect_artifact(path, "baseline-package")
            return publication

        def phase_runner_factory(trusted_source: TrustedSource) -> BugFixPhaseRunner:
            return BugFixPhaseRunner(
                trusted_source=trusted_source,
                workspace_builder=workspace,
                checkpoint_manager=checkpoint,
                evidence_store=evidence,
                container=request.evaluator_container,
                version=request.context.entry.environment_setup_version,
                project_paths=request.context.entry.project_paths,
                inventory_reader=ownership.read_app_inventory,
            )

        return cls(
            evidence_store=evidence,
            workspace_builder=workspace,
            checkpoint_manager=checkpoint,
            phase_runner_factory=phase_runner_factory,
            ownership_api=ownership,
            baseline_publisher=baseline_publisher,
        )

    def run(
        self,
        request: BugFixLifecycleRequest,
        agent_runner: ProductionAgentRunner,
        cleanup_lease: CleanupLease | None = None,
    ) -> BugFixResult:
        active_cleanup_lease = cleanup_lease or CleanupLease.for_lifecycle(request.provisioned_resources)
        if active_cleanup_lease.resources != request.provisioned_resources:
            raise ValueError("Cleanup lease resources must match the lifecycle request")
        if not active_cleanup_lease.is_lifecycle_owner:
            raise ValueError("Cleanup lease must be owned by the lifecycle")
        WorkflowExecution(request.provisioned_resources).begin_lifecycle()
        result: BugFixResult | None = None
        propagate: BaseException | None = None
        agent_execution_error: BaseException | None = None
        trusted_source: TrustedSource | None = None
        s0: CheckpointManifest | None = None
        sf: CheckpointManifest | None = None
        analysis: SubmissionAnalysis | None = None
        full_patch = ""
        full_patch_hash: str | None = None
        submission_frozen = False
        timeout = False
        execution_mode = "replay" if request.replay_patch is not None else "live"
        agent_stdout: str | None = None
        agent_stderr: str | None = None
        agent_error: AgentError | None = None
        phases: dict[str, BugFixPhaseResult] = {}
        result_persisted = False
        result_finalized = False
        barrier_error: BugFixLifecycleInfrastructureError | None = None
        persisted_failure_phase: str | None = None

        try:
            phases = _empty_phases()
            try:
                trusted_source, s0 = self._setup(request)
            except Exception as error:  # noqa: BLE001 - setup failure must produce a final result
                self._save_exception("setup-failure.txt", error)
                phases = _infrastructure_setup_phases(str(error))
                self._persist_phase_results(phases)
                result = self._create_result(
                    request,
                    phases,
                    full_patch="",
                    full_patch_hash=None,
                    trusted_source=None,
                    s0=None,
                    sf=None,
                    analysis=None,
                    execution_mode=execution_mode,
                    timeout=False,
                    agent_stdout=None,
                    agent_stderr=None,
                    error_message=f"Lifecycle setup failed: {error}",
                )

            if result is None and trusted_source is not None and s0 is not None:
                if request.replay_patch is None:
                    agent_context = replace(
                        request.context,
                        repo_path=request.paths.agent_workspace,
                        container=request.agent_runtime.container,
                    )
                    try:
                        agent_context.metrics, agent_context.experiment = agent_runner(
                            agent_context,
                            request.agent_execution_policy,
                        )
                    except AgentTimeoutError as error:
                        timeout = True
                        agent_context.metrics = error.metrics
                        agent_context.experiment = error.config
                        agent_stdout = error.stdout
                        agent_stderr = error.stderr
                    except AgentError as error:
                        agent_error = error
                        agent_stdout = getattr(error, "stdout", None)
                        agent_stderr = getattr(error, "stderr", None)
                    except BaseException as error:  # noqa: BLE001 - persist diagnostics before propagation
                        agent_execution_error = error
                        propagate = error
                        self._save_exception("lifecycle-emergency.txt", error)
                    finally:
                        request.context.metrics = agent_context.metrics
                        request.context.experiment = agent_context.experiment

                barrier_error = self._establish_isolation_barrier(request, agent_execution_error)
                if barrier_error is None:
                    if request.replay_patch is not None:
                        full_patch = self._read_replay_patch(request)
                        submission_frozen = True
                    else:
                        try:
                            full_patch = self._freeze_submission(
                                request.paths.agent_workspace,
                                trusted_source.commit,
                            )
                            submission_frozen = True
                        except GeneratedSubmissionError as error:
                            full_patch = error.generated_patch or ""
                            submission_frozen = True
                            analysis = _globally_invalid_analysis(full_patch, str(error))
                            self._save_exception("submission-freeze-invalid.txt", error)
                        except EmptyDiffError as error:
                            submission_frozen = True
                            self._save_exception("submission-freeze-empty.txt", error)
                        except Exception as error:  # noqa: BLE001 - freeze diagnostics after any agent outcome
                            self._save_exception("submission-freeze-failure.txt", error)
                            if propagate is None and agent_error is None:
                                propagate = error

                if submission_frozen:
                    full_patch_hash = sha256_text(full_patch)
                    self._persist_frozen_submission(
                        full_patch,
                        full_patch_hash,
                        agent_stdout,
                        agent_stderr,
                    )

                if barrier_error is not None:
                    phases = _isolation_barrier_phases(str(barrier_error))
                    self._persist_phase_results(phases)
                    result = self._create_result(
                        request,
                        phases,
                        full_patch="",
                        full_patch_hash=None,
                        trusted_source=trusted_source,
                        s0=s0,
                        sf=None,
                        analysis=None,
                        execution_mode=execution_mode,
                        timeout=timeout,
                        agent_stdout=agent_stdout,
                        agent_stderr=agent_stderr,
                        error_message=str(barrier_error),
                    )
                elif propagate is not None:
                    phases = _infrastructure_setup_phases(str(propagate))
                    self._persist_phase_results(phases)
                    result = self._create_result(
                        request,
                        phases,
                        full_patch=full_patch,
                        full_patch_hash=full_patch_hash,
                        trusted_source=trusted_source,
                        s0=s0,
                        sf=None,
                        analysis=None,
                        execution_mode=execution_mode,
                        timeout=timeout,
                        agent_stdout=agent_stdout,
                        agent_stderr=agent_stderr,
                        error_message=str(propagate),
                    )
                elif agent_error is not None:
                    phases = _agent_failure_phases(str(agent_error))
                    self._persist_phase_results(phases)
                    result = self._create_result(
                        request,
                        phases,
                        full_patch=full_patch,
                        full_patch_hash=full_patch_hash,
                        trusted_source=trusted_source,
                        s0=s0,
                        sf=None,
                        analysis=None,
                        execution_mode=execution_mode,
                        timeout=False,
                        agent_stdout=agent_stdout,
                        agent_stderr=agent_stderr,
                        error_message=str(agent_error),
                    )
                    propagate = agent_error
                else:
                    try:
                        if analysis is None:
                            analysis = self._analyzer(
                                request.paths.agent_workspace,
                                full_patch,
                                trusted_source.commit,
                                request.context.entry.project_paths,
                            )
                        phase_runner = self._phase_runner_factory(trusted_source)
                        phases, sf = self._run_phases(
                            request,
                            phase_runner,
                            analysis,
                            s0,
                            phases,
                        )
                        result = self._create_result(
                            request,
                            phases,
                            full_patch=full_patch,
                            full_patch_hash=full_patch_hash,
                            trusted_source=trusted_source,
                            s0=s0,
                            sf=sf,
                            analysis=analysis,
                            execution_mode=execution_mode,
                            timeout=timeout,
                            agent_stdout=agent_stdout,
                            agent_stderr=agent_stderr,
                            error_message=_phase_error_message(phases),
                        )
                    except PhaseExecutionInfrastructureError as error:
                        propagate = error.original
                        persisted_failure_phase = error.phase_name
                        sf = error.fixed_checkpoint
                        self._save_exception("lifecycle-emergency.txt", error.original)
                        self._persist_phase_results(
                            phases,
                            skip_evidence_names={error.phase_name},
                        )
                        result = self._create_result(
                            request,
                            phases,
                            full_patch=full_patch,
                            full_patch_hash=full_patch_hash,
                            trusted_source=trusted_source,
                            s0=s0,
                            sf=sf,
                            analysis=analysis,
                            execution_mode=execution_mode,
                            timeout=timeout,
                            agent_stdout=agent_stdout,
                            agent_stderr=agent_stderr,
                            error_message=str(error.original),
                        )
                    except BaseException as error:  # noqa: BLE001 - final evidence precedes propagation
                        propagate = error
                        self._save_exception("lifecycle-emergency.txt", error)
                        self._persist_phase_results(phases)
                        result = self._create_result(
                            request,
                            phases,
                            full_patch=full_patch,
                            full_patch_hash=full_patch_hash,
                            trusted_source=trusted_source,
                            s0=s0,
                            sf=sf,
                            analysis=analysis,
                            execution_mode=execution_mode,
                            timeout=timeout,
                            agent_stdout=agent_stdout,
                            agent_stderr=agent_stderr,
                            error_message=str(error),
                        )

            result = _require_result(result)
            result = result.model_copy(update={"artifact_manifest": self._artifact_manifest(request)})
            result_finalized = True
            self._persist_result(request, result)
            result_persisted = True
        except BaseException as error:  # noqa: BLE001 - all failures need final evidence and cleanup
            if propagate is None:
                propagate = error
            self._save_exception("lifecycle-emergency.txt", error)
            if result is None:
                phases = _infrastructure_setup_phases(str(error))
                result = self._create_result(
                    request,
                    phases,
                    full_patch=full_patch,
                    full_patch_hash=full_patch_hash,
                    trusted_source=trusted_source,
                    s0=s0,
                    sf=sf,
                    analysis=analysis,
                    execution_mode=execution_mode,
                    timeout=timeout,
                    agent_stdout=agent_stdout,
                    agent_stderr=agent_stderr,
                    error_message=str(error),
                )
            if not result_persisted:
                self._persist_phase_results(
                    phases,
                    skip_evidence_names=({persisted_failure_phase} if persisted_failure_phase is not None else ()),
                )
                if not result_finalized:
                    result = result.model_copy(update={"artifact_manifest": self._artifact_manifest(request)})
                    result_finalized = True
                try:
                    self._persist_result(request, result)
                    result_persisted = True
                except BaseException as persistence_error:  # noqa: BLE001 - cleanup still must run
                    persistence_error.add_note(f"Primary lifecycle failure: {propagate}")
                    propagate = persistence_error
        finally:
            cleanup_error = active_cleanup_lease.cleanup_as_lifecycle(lambda: self._cleanup(request, agent_execution_error))

        if cleanup_error is not None:
            if propagate is not None:
                raise cleanup_error from propagate
            raise cleanup_error
        if propagate is not None:
            raise propagate.with_traceback(propagate.__traceback__)
        return result

    def _setup(
        self,
        request: BugFixLifecycleRequest,
    ) -> tuple[TrustedSource, CheckpointManifest]:
        baseline = request.paths.baseline_workspace
        self._setup_repo(request.context.entry, baseline)
        self._save_step("01-repository-prebuild.json", {"status": "complete"})
        self._baseline_publisher(
            baseline,
            tuple(request.context.entry.project_paths),
        )
        self._save_step("02-baseline-publication.json", {"status": "complete"})
        _remove_baseline_build_artifacts(
            baseline,
            request.context.entry.project_paths,
        )
        self._copy_problem(request.context.entry, baseline)
        self._save_step("03-problem-copy.json", {"status": "complete"})
        self._set_runtime(baseline, request.context.entry.project_paths)
        self._save_step("04-runtime.json", {"status": "complete"})
        self._commit_changes(baseline, "Prepare bug-fix production baseline")
        self._save_step("05-preparation-commit.json", {"status": "complete"})

        identity = self._ownership_api.get_container_identity()
        if identity.container_id != request.expected_container_id:
            raise BugFixLifecycleInfrastructureError("Recorded container identity does not match the expected owned container")
        apps = tuple(self._ownership_api.read_app_inventory())
        self._save_step("06-container-identity.json", identity.to_dict())
        inventory_path = self._evidence_store.save_inventory(
            "baseline",
            [app.to_dict() for app in apps],
            [app.to_dict() for app in apps],
        )
        self._evidence_store.protect_artifact(
            inventory_path,
            "lifecycle-evidence",
        )
        s0 = self._checkpoint_manager.capture("baseline", apps)
        self._save_step("baseline-checkpoint.json", s0.to_dict())
        trusted_source = self._workspace_builder.capture_trusted_source(baseline)
        self._save_step(
            "07-trusted-source.json",
            {
                "commit": trusted_source.commit,
                "repository": str(trusted_source.repository),
            },
        )
        self._workspace_builder.create_agent_workspace(trusted_source)
        self._save_step("08-agent-workspace.json", {"status": "complete"})
        self._workspace_builder.remove_baseline_workspace()
        self._save_step("09-baseline-removal.json", {"status": "complete"})
        return trusted_source, s0

    def _read_replay_patch(self, request: BugFixLifecycleRequest) -> str:
        replay_patch = request.replay_patch
        if replay_patch is None:
            raise ValueError("Replay patch is required")
        protected_patch = require_strict_descendant(
            replay_patch,
            request.paths.protected_root,
            "replay patch",
            "protected root",
        )
        reject_reparse_components(protected_patch, request.paths.protected_root)
        if not protected_patch.is_file() or protected_patch.is_symlink():
            raise GeneratedOutputError(f"Replay patch must be a protected regular file: {protected_patch}")
        return protected_patch.read_text(encoding="utf-8")

    def _persist_frozen_submission(
        self,
        patch: str,
        patch_hash: str,
        stdout: str | None,
        stderr: str | None,
    ) -> None:
        patch_path = self._evidence_store.save_submission("generated-full.patch", patch)
        protected_patch = self._evidence_store.protect_artifact(
            patch_path,
            "generated-submission",
        )
        self._save_step(
            "10-frozen-submission.json",
            {
                "path": str(self._evidence_store.relative_protected_path(protected_patch)),
                "sha256": patch_hash,
            },
        )
        if stdout is not None:
            path = self._evidence_store.save_text("agent-stdout.txt", stdout)
            self._evidence_store.protect_artifact(path, "agent-diagnostics")
        if stderr is not None:
            path = self._evidence_store.save_text("agent-stderr.txt", stderr)
            self._evidence_store.protect_artifact(path, "agent-diagnostics")

    def _run_phases(
        self,
        request: BugFixLifecycleRequest,
        runner: BugFixPhaseRunner,
        analysis: SubmissionAnalysis,
        s0: CheckpointManifest,
        phases: dict[str, BugFixPhaseResult],
    ) -> tuple[dict[str, BugFixPhaseResult], CheckpointManifest | None]:
        submission = analysis.submission
        sf: CheckpointManifest | None = None

        try:
            if analysis.test_is_safe:
                phases["test_red"] = runner.run_test_red(submission, s0)
                phases["test_gold"] = runner.run_test_gold(
                    submission,
                    s0,
                    request.context.entry.patch,
                )
            else:
                phases["test_red"] = self._persist_phase(
                    "test-red",
                    make_invalid_submission_phase(analysis.test_error or "Invalid generated test."),
                )
                phases["test_gold"] = self._persist_phase(
                    "test-gold",
                    make_invalid_submission_phase(analysis.test_error or "Invalid generated test."),
                )

            if analysis.fix_is_safe:
                phases["fix_build"], sf = runner.run_fix_build(submission, s0)
            else:
                phases["fix_build"] = self._persist_phase(
                    "fix-build",
                    make_invalid_submission_phase(analysis.fix_error or "Invalid generated fix."),
                )

            if not analysis.test_is_safe:
                phases["generated_pair"] = self._persist_phase(
                    "generated-pair",
                    make_invalid_submission_phase(analysis.test_error or "Invalid generated test."),
                )
            elif sf is None:
                phases["generated_pair"] = self._persist_phase(
                    "generated-pair",
                    _prerequisite_phase(
                        phases["fix_build"],
                        "Fixed checkpoint is unavailable.",
                    ),
                )
            elif not phases["test_red"].executed_tests:
                phases["generated_pair"] = self._persist_phase(
                    "generated-pair",
                    _prerequisite_phase(
                        phases["test_red"],
                        "The red phase did not execute the generated test.",
                    ),
                )
            else:
                phases["generated_pair"] = runner.run_generated_pair(
                    submission,
                    sf,
                    phases["test_red"],
                )

            if sf is not None:
                phases["benchmark_fix"] = runner.run_benchmark_fix(
                    submission,
                    sf,
                    request.context.entry.test_patch,
                    (
                        *request.context.entry.fail_to_pass,
                        *request.context.entry.pass_to_pass,
                    ),
                )
            else:
                phases["benchmark_fix"] = self._persist_phase(
                    "benchmark-fix",
                    _prerequisite_phase(
                        phases["fix_build"],
                        "Fixed checkpoint is unavailable.",
                    ),
                )
        except PhaseExecutionInfrastructureError as error:
            field_name = _phase_result_field(error.phase_name)
            phases[field_name] = error.result
            error.fixed_checkpoint = sf
            raise
        return phases, sf

    def _persist_phase(
        self,
        name: str,
        phase: BugFixPhaseResult,
    ) -> BugFixPhaseResult:
        self._evidence_store.save_phase(name, phase)
        return phase

    def _persist_phase_results(
        self,
        phases: Mapping[str, BugFixPhaseResult],
        *,
        skip_evidence_names: Iterable[str] = (),
    ) -> None:
        skipped = set(skip_evidence_names)
        names = {
            "test_red": "test-red",
            "test_gold": "test-gold",
            "fix_build": "fix-build",
            "generated_pair": "generated-pair",
            "benchmark_fix": "benchmark-fix",
        }
        for field_name, evidence_name in names.items():
            if evidence_name in skipped:
                continue
            self._evidence_store.save_phase(evidence_name, phases[field_name])

    def _create_result(
        self,
        request: BugFixLifecycleRequest,
        phases: Mapping[str, BugFixPhaseResult],
        *,
        full_patch: str,
        full_patch_hash: str | None,
        trusted_source: TrustedSource | None,
        s0: CheckpointManifest | None,
        sf: CheckpointManifest | None,
        analysis: SubmissionAnalysis | None,
        execution_mode: str,
        timeout: bool,
        agent_stdout: str | None,
        agent_stderr: str | None,
        error_message: str | None,
    ) -> BugFixResult:
        submission = analysis.submission if analysis is not None else None
        effective_error_message = error_message
        if timeout and effective_error_message is None:
            effective_error_message = "Agent timed out"
        result = BugFixResult(
            **BugFixResult._base_fields(request.context),
            output=full_patch,
            error_message=effective_error_message,
            timeout=timeout,
            runtime_isolation="database-checkpointed-single-container",
            execution_mode=execution_mode,
            trusted_source_commit=trusted_source.commit if trusted_source else None,
            generated_patch_hash=full_patch_hash,
            generated_fix_hash=submission.fix_patch_hash if submission else None,
            generated_test_hash=submission.test_patch_hash if submission else None,
            baseline_checkpoint_hash=s0.sha256 if s0 else None,
            fixed_checkpoint_hash=sf.sha256 if sf else None,
            agent_stdout=agent_stdout,
            agent_stderr=agent_stderr,
            provenance={
                "container_id": request.expected_container_id,
                "container_invocation_id": request.expected_container_invocation_id,
            },
            test_red=phases["test_red"],
            test_gold=phases["test_gold"],
            fix_build=phases["fix_build"],
            generated_pair=phases["generated_pair"],
            benchmark_fix=phases["benchmark_fix"],
            generated_test_pre_patch_failed=phases["test_red"].status is BugFixPhaseStatus.PASSED,
            generated_test_post_patch_passed=phases["generated_pair"].status is BugFixPhaseStatus.PASSED,
            build=phases["fix_build"].status is BugFixPhaseStatus.PASSED,
            benchmark_test_passed=phases["benchmark_fix"].status is BugFixPhaseStatus.PASSED,
        )
        return self._with_result_projections(result)

    @staticmethod
    def _with_result_projections(result: BugFixResult) -> BugFixResult:
        resolution = result.metric_status(BugFixMetricName.RESOLUTION)
        metric_statuses = tuple(result.metric_status(metric) for metric in BugFixMetricName)
        unknown_statuses = {
            BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
            BugFixPhaseStatus.NOT_RUN,
        }
        return result.model_copy(
            update={
                "resolved": resolution is BugFixPhaseStatus.PASSED,
                "infrastructure_failure": all(status in unknown_statuses for status in metric_statuses),
            }
        )

    def _artifact_manifest(
        self,
        request: BugFixLifecycleRequest,
    ) -> dict[str, str]:
        artifacts: dict[str, str] = {}
        for root in (request.paths.checkpoints, request.paths.final_results):
            if not root.is_dir():
                continue
            for path in sorted(
                (candidate for candidate in root.rglob("*") if candidate.is_file() and not candidate.is_symlink()),
                key=lambda candidate: str(candidate).casefold(),
            ):
                artifacts[str(path.relative_to(request.paths.protected_root))] = sha256_file(path)
        return artifacts

    def _persist_result(
        self,
        request: BugFixLifecycleRequest,
        result: BugFixResult,
    ) -> None:
        self._write_result_jsonl(
            request.context.result_dir / f"{request.context.entry.instance_id}.jsonl",
            result,
        )
        self._evidence_store.save_final_result(result)

    @staticmethod
    def _write_result_jsonl(
        destination: Path,
        result: BugFixResult,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _atomic_text(
            destination,
            json.dumps(result.model_dump(mode="json")) + "\n",
        )
        logger.info(f"Saved evaluation result for {result.instance_id} to {destination}")

    def _save_step(self, name: str, payload: object) -> None:
        path = self._evidence_store.save_text(
            name,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
        )
        self._evidence_store.protect_artifact(path, "lifecycle-evidence")

    def _save_exception(self, name: str, error: BaseException) -> None:
        try:
            path = self._evidence_store.save_text(
                name,
                "".join(
                    traceback.format_exception(
                        type(error),
                        error,
                        error.__traceback__,
                    )
                ),
            )
            self._evidence_store.protect_artifact(
                path,
                "lifecycle-diagnostics",
            )
        except Exception:
            logger.exception(f"Failed to persist lifecycle diagnostic {name}")

    def _establish_isolation_barrier(self, request: BugFixLifecycleRequest, execution_error: BaseException | None) -> BugFixLifecycleInfrastructureError | None:
        outcomes: dict[str, dict[str, str]] = {}
        errors: list[str] = []
        for name, operation in (
            ("close_process_group", lambda: self._close_agent_group(execution_error)),
            ("stop_agent_clients", lambda: self._stop_agent_clients(request)),
            ("stop_agent_sessions", self._ownership_api.stop_agent_sessions),
        ):
            try:
                operation()
            except Exception as error:  # noqa: BLE001 - every barrier operation must be attempted and recorded
                errors.append(f"{name}: {error}")
                outcomes[name] = {
                    "status": "infrastructure_error",
                    "error": str(error),
                }
            else:
                outcomes[name] = {"status": "verified"}

        if errors:
            barrier_error = BugFixLifecycleInfrastructureError("Isolation barrier failed: " + "; ".join(errors))
            try:
                self._save_step(
                    "isolation-barrier-failure.json",
                    {
                        "status": "infrastructure_error",
                        "operations": outcomes,
                    },
                )
            except Exception:
                logger.exception("Failed to persist isolation barrier diagnostic")
            return barrier_error

        self._save_step(
            "10-isolation-barrier.json",
            {
                "status": "verified",
                "operations": outcomes,
            },
        )
        return None

    def _close_agent_group(self, execution_error: BaseException | None) -> None:
        self._ownership_api.close_contained_group()
        self._verify_agent_execution_closed(execution_error)

    @staticmethod
    def _verify_agent_execution_closed(execution_error: BaseException | None) -> None:
        if isinstance(execution_error, ContainedProcessInfrastructureError | KeyboardInterrupt):
            raise BugFixLifecycleInfrastructureError("Contained agent process shutdown was not verified")

    def _cleanup(self, request: BugFixLifecycleRequest, execution_error: BaseException | None) -> CleanupInfrastructureError | None:
        execution = WorkflowExecution(request.provisioned_resources)

        def verify_shutdown() -> None:
            self._close_agent_group(execution_error)
            self._stop_agent_clients(request, execution_error)
            self._ownership_api.stop_agent_sessions()

        return LifecycleCleanup(
            request.provisioned_resources,
            self._ownership_api,
            stop_agent_clients=(lambda: execution.verify_shutdown(verify_shutdown) if execution.enabled else self._stop_agent_clients(request, execution_error)),
        ).run()

    @staticmethod
    def _stop_agent_clients(request: BugFixLifecycleRequest, execution_error: BaseException | None = None) -> None:
        clients = request.agent_execution_policy.managed_clients
        if clients is not None:
            clients.stop()
        ProductionBugFixLifecycle._verify_agent_execution_closed(execution_error)


def _empty_phases() -> dict[str, BugFixPhaseResult]:
    return {
        "test_red": make_not_run_phase("Lifecycle phase has not run."),
        "test_gold": make_not_run_phase("Lifecycle phase has not run."),
        "fix_build": make_not_run_phase("Lifecycle phase has not run."),
        "generated_pair": make_not_run_phase("Lifecycle phase has not run."),
        "benchmark_fix": make_not_run_phase("Lifecycle phase has not run."),
    }


def _require_result(result: BugFixResult | None) -> BugFixResult:
    if result is None:
        raise RuntimeError("Bug-fix lifecycle did not produce a result")
    return result


def _infrastructure_setup_phases(error: str) -> dict[str, BugFixPhaseResult]:
    reason = f"Lifecycle infrastructure prerequisite failed: {error}"
    return {name: make_not_run_phase(reason) for name in _empty_phases()}


def _agent_failure_phases(error: str) -> dict[str, BugFixPhaseResult]:
    return {name: make_not_run_phase(f"Agent execution failed: {error}") for name in _empty_phases()}


def _isolation_barrier_phases(error: str) -> dict[str, BugFixPhaseResult]:
    now = datetime.now(UTC)
    infrastructure_phase = BugFixPhaseResult(
        status=BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
        started_at=now,
        completed_at=now,
        error_message=error,
    )
    return {
        "test_red": infrastructure_phase,
        "test_gold": infrastructure_phase,
        "fix_build": infrastructure_phase,
        "generated_pair": make_not_run_phase("Isolation barrier prerequisite is unknown."),
        "benchmark_fix": make_not_run_phase("Isolation barrier prerequisite is unknown."),
    }


def _prerequisite_phase(
    prerequisite: BugFixPhaseResult,
    reason: str,
) -> BugFixPhaseResult:
    if prerequisite.status is BugFixPhaseStatus.INVALID_SUBMISSION:
        return make_invalid_submission_phase(reason)
    return make_not_run_phase(reason)


def _phase_result_field(phase_name: str) -> str:
    fields = {
        "test-red": "test_red",
        "test-gold": "test_gold",
        "fix-build": "fix_build",
        "generated-pair": "generated_pair",
        "benchmark-fix": "benchmark_fix",
    }
    try:
        return fields[phase_name]
    except KeyError as error:
        raise ValueError(f"Unknown bug-fix phase: {phase_name}") from error


def _remove_baseline_build_artifacts(
    baseline: Path,
    project_paths: Sequence[str],
) -> None:
    for project_path in dict.fromkeys(project_paths):
        project_root = baseline / Path(project_path.replace("\\", "/"))
        for name in ("output", ".alpackages"):
            artifact_root = project_root / name
            if artifact_root.is_dir():
                remove_tree(artifact_root)


def _phase_error_message(
    phases: Mapping[str, BugFixPhaseResult],
) -> str | None:
    failures = [f"{name}: {phase.error_message or phase.status.value}" for name, phase in phases.items() if phase.status is not BugFixPhaseStatus.PASSED]
    return "; ".join(failures) if failures else None


def _default_powershell_runner(
    request: BugFixLifecycleRequest,
) -> PowerShellRunner:
    environment = {
        **os.environ,
        "BC_SERVER_USERNAME": request.evaluator_container.username,
        "BC_SERVER_PASSWORD": request.evaluator_container.password,
        "BC_COMPANY": request.evaluator_container.company,
    }

    def run(script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "pwsh",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    return run


def _default_cleanup_powershell_runner() -> PowerShellRunner:
    def run(script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "pwsh",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            env=os.environ,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    return run


class PowerShellLifecycleOwnershipApi:
    def __init__(
        self,
        resources: ProvisionedLifecycleResources,
        evidence_store: EvidenceStore | None,
        powershell_runner: PowerShellRunner,
        *,
        module_path: Path | None = None,
    ) -> None:
        self._resources = resources
        self._paths = resources.paths
        self._evidence_store = evidence_store
        self._runner = powershell_runner
        self._module_path = (module_path or Path(__file__).parents[4] / "scripts" / "BugFixLifecycle.psm1").resolve()

    def get_container_identity(self) -> ContainerIdentity:
        payload = self._invoke_json(
            "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    f"Import-Module {_ps_quote(self._module_path)} -Force",
                    "$result = Get-BCBenchContainerIdentity `",
                    f"  -ContainerName {_ps_quote(self._container_name)} `",
                    f"  -ExpectedContainerId {_ps_quote(self._container_id)} `",
                    f"  -ExpectedInvocationId {_ps_quote(self._invocation_id)}",
                    "$result | ConvertTo-Json -Compress -Depth 8",
                )
            )
        )
        return ContainerIdentity.from_dict(payload)

    def read_app_inventory(self) -> tuple[AppInventoryEntry, ...]:
        payload = self._invoke_json_value(
            "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    f"Import-Module {_ps_quote(self._module_path)} -Force",
                    "$result = @(Get-BCBenchAppInventory `",
                    f"  -ContainerName {_ps_quote(self._container_name)} `",
                    f"  -ExpectedContainerId {_ps_quote(self._container_id)} `",
                    f"  -ExpectedInvocationId {_ps_quote(self._invocation_id)})",
                    "$result | ConvertTo-Json -Compress -Depth 8",
                )
            )
        )
        if not isinstance(payload, list) or not all(isinstance(item, Mapping) for item in payload):
            raise BugFixLifecycleInfrastructureError("Application inventory PowerShell output must be a list")
        return tuple(AppInventoryEntry.from_dict(item) for item in payload)

    def close_contained_group(self) -> None:
        # The synchronous contained-process wrapper closes its Windows job before returning.
        return None

    def stop_agent_sessions(self) -> None:
        self._stop_service("agent-session-stop")

    def verify_container_ownership(self) -> None:
        identity = self.get_container_identity()
        if identity.container_id != self._container_id:
            raise CleanupInfrastructureError("Container ownership changed before cleanup")

    def stop_evaluator_processes(self) -> None:
        self._stop_service("evaluator-process-stop", persist_evidence=False)

    def remove_bc_user(self) -> None:
        self._invoke(
            "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    f"Import-Module {_ps_quote(self._module_path)} -Force",
                    "Remove-BCBenchAgentBcUser `",
                    f"  -ContainerName {_ps_quote(self._container_name)} `",
                    f"  -Username {_ps_quote(self._resources.agent_bc_username)} `",
                    f"  -ExpectedContainerId {_ps_quote(self._container_id)} `",
                    f"  -ExpectedInvocationId {_ps_quote(self._invocation_id)}",
                )
            )
        )

    def remove_container_and_verify(self) -> None:
        self._invoke(
            "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    f"Import-Module {_ps_quote(self._module_path)} -Force",
                    "Remove-BCBenchContainerAndVerify `",
                    f"  -ContainerName {_ps_quote(self._container_name)} `",
                    f"  -ExpectedContainerId {_ps_quote(self._container_id)} `",
                    f"  -ExpectedInvocationId {_ps_quote(self._invocation_id)}",
                )
            )
        )

    def remove_acl(self) -> None:
        acl_paths = validate_cleanup_acl_paths(self._resources)
        encoded_paths = json.dumps([str(path) for path in acl_paths])
        self._invoke(
            "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    f"Import-Module {_ps_quote(self._module_path)} -Force",
                    f"$paths = '{_ps_single_quote(encoded_paths)}' | ConvertFrom-Json",
                    "$transaction = [PSCustomObject]@{",
                    f"  Sid = {_ps_quote(self._resources.agent_os_sid)}",
                    "  ModifiedPaths = [System.Collections.Generic.List[string]]::new()",
                    "  CleanupComplete = $false",
                    "}",
                    "foreach ($path in @($paths)) { $transaction.ModifiedPaths.Add([string]$path) }",
                    "Remove-BCBenchAgentAcl -Transaction $transaction",
                )
            )
        )

    def remove_local_identity(self) -> None:
        self._invoke(
            "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    f"Import-Module {_ps_quote(self._module_path)} -Force",
                    "Remove-BCBenchAgentIdentity `",
                    f"  -Username {_ps_quote(self._resources.agent_os_username)}",
                )
            )
        )

    def remove_roots(self) -> None:
        plugin_root = self._paths.agent_tools / "plugins"
        if plugin_root.exists() or plugin_root.is_symlink() or plugin_root.is_junction():
            validate_agent_plugin_root(self._resources)
        entry_paths = tuple(getattr(self._paths, name) for name in ENTRY_MANAGED_PATH_NAMES)
        external_roots = validate_owned_lifecycle_roots(
            self._resources.compiler_helper_roots,
            self._paths,
            self._invocation_id,
        )

        for path in entry_paths:
            reject_reparse_components(path, self._paths.entry_root)
            require_strict_descendant(path, self._paths.entry_root, "managed entry root", "entry_root")
            if path.exists() and not path.is_dir():
                raise CleanupInfrastructureError(f"Managed entry root is not a directory: {path}")

        for path in entry_paths:
            if path.exists():
                remove_tree(path)
            if path.exists():
                raise CleanupInfrastructureError(f"Managed entry root still exists after removal: {path}")

        for owned_root in external_roots:
            remove_tree(owned_root.path)
            if owned_root.path.exists():
                raise CleanupInfrastructureError(f"Compiler/helper root still exists after removal: {owned_root.path}")

        entry_root = self._paths.entry_root
        reject_reparse_components(entry_root, entry_root)
        if entry_root.exists():
            if not entry_root.is_dir():
                raise CleanupInfrastructureError(f"Entry root is not a directory: {entry_root}")
            remaining = tuple(entry_root.iterdir())
            if remaining:
                raise CleanupInfrastructureError("Entry root contains unowned paths and was preserved: " + ", ".join(str(path) for path in remaining))
            entry_root.rmdir()

    def disable_local_identity(self) -> None:
        self._invoke(
            "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    f"Import-Module {_ps_quote(self._module_path)} -Force",
                    "Disable-BCBenchAgentIdentity `",
                    f"  -Username {_ps_quote(self._resources.agent_os_username)}",
                    "Assert-BCBenchAgentIdentityDisabled `",
                    f"  -Username {_ps_quote(self._resources.agent_os_username)}",
                )
            )
        )

    @property
    def _container_name(self) -> str:
        return self._resources.container_name

    @property
    def _container_id(self) -> str:
        return self._resources.expected_container_id

    @property
    def _invocation_id(self) -> str:
        return self._resources.expected_container_invocation_id

    def _stop_service(
        self,
        evidence_name: str,
        *,
        persist_evidence: bool = True,
    ) -> None:
        payload = self._invoke_json(
            "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    f"Import-Module {_ps_quote(self._module_path)} -Force",
                    "$result = Stop-BCBenchServiceTier `",
                    f"  -ContainerName {_ps_quote(self._container_name)} `",
                    f"  -ExpectedContainerId {_ps_quote(self._container_id)} `",
                    f"  -ExpectedInvocationId {_ps_quote(self._invocation_id)}",
                    "$result | ConvertTo-Json -Compress -Depth 8",
                )
            )
        )
        if not persist_evidence:
            return
        if self._evidence_store is None:
            raise BugFixLifecycleInfrastructureError("Lifecycle evidence store is unavailable")
        path = self._evidence_store.save_text(
            f"{evidence_name}.json",
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
        )
        self._evidence_store.protect_artifact(path, "lifecycle-evidence")

    def _invoke_json(self, script: str) -> Mapping[str, object]:
        payload = self._invoke_json_value(script)
        if not isinstance(payload, Mapping):
            raise BugFixLifecycleInfrastructureError("Lifecycle PowerShell JSON must be an object")
        return payload

    def _invoke_json_value(self, script: str) -> object:
        result = self._invoke(script)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            raise BugFixLifecycleInfrastructureError("Lifecycle PowerShell returned no JSON")
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError as error:
            raise BugFixLifecycleInfrastructureError("Lifecycle PowerShell returned malformed JSON") from error

    def _invoke(self, script: str) -> PowerShellResult:
        try:
            result = self._runner(script)
        except (OSError, subprocess.SubprocessError) as error:
            raise BugFixLifecycleInfrastructureError(f"Lifecycle PowerShell invocation failed: {error}") from error
        if result.returncode != 0:
            diagnostics = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
            raise BugFixLifecycleInfrastructureError(f"Lifecycle PowerShell failed with exit code {result.returncode}: {diagnostics}")
        return result


def run_bugfix_production_lifecycle(
    request: BugFixLifecycleRequest,
    agent_runner: ProductionAgentRunner,
    *,
    powershell_runner: PowerShellRunner | None = None,
) -> BugFixResult:
    lifecycle = ProductionBugFixLifecycle.from_request(
        request,
        powershell_runner=powershell_runner,
    )
    return lifecycle.run(request, agent_runner)


BugFixProductionLifecycle = ProductionBugFixLifecycle


def _atomic_json(destination: Path, payload: object) -> None:
    _atomic_text(
        destination,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )


def _atomic_text(destination: Path, content: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _ps_single_quote(value: str) -> str:
    return value.replace("'", "''")


def _ps_quote(value: str | Path) -> str:
    return f"'{_ps_single_quote(str(value))}'"
