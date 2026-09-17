from __future__ import annotations

import json
import os
import subprocess
import tempfile
import traceback
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from bcbench.agent.shared.contained_process import AgentExecutionPolicy
from bcbench.dataset import BugFixEntry, TestEntry
from bcbench.evaluate import bugfix_output
from bcbench.evaluate.bugfix_lifecycle.checkpoint import CheckpointManager, PowerShellResult, PowerShellRunner
from bcbench.evaluate.bugfix_lifecycle.evidence import EvidenceStore, sha256_file, sha256_text
from bcbench.evaluate.bugfix_lifecycle.models import (
    AppInventoryEntry,
    BugFixLifecycleRequest,
    CheckpointManifest,
    ContainerIdentity,
    ProjectPublication,
    SubmissionAnalysis,
    TrustedSource,
)
from bcbench.evaluate.bugfix_lifecycle.path_safety import (
    reject_reparse_components,
    require_strict_descendant,
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

    def quarantine(self, errors: tuple[str, ...]) -> None: ...


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


class BugFixProductionLifecycle:
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
    ) -> BugFixProductionLifecycle:
        evidence = EvidenceStore(request.paths)
        workspace = TrustedWorkspaceBuilder(request.paths)
        runner = powershell_runner or _default_powershell_runner(request)
        ownership = PowerShellLifecycleOwnershipApi(
            request,
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
    ) -> BugFixResult:
        result: BugFixResult | None = None
        propagate: BaseException | None = None
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
        phases = _empty_phases()
        result_persisted = False

        try:
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
                if request.replay_patch is not None:
                    full_patch = self._read_replay_patch(request)
                    submission_frozen = True
                else:
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
                        propagate = error
                        self._save_exception("lifecycle-emergency.txt", error)
                    finally:
                        request.context.metrics = agent_context.metrics
                        request.context.experiment = agent_context.experiment
                        try:
                            self._ownership_api.close_contained_group()
                            self._ownership_api.stop_agent_sessions()
                        except Exception as error:  # noqa: BLE001 - close all agent-owned sessions
                            self._save_exception("agent-session-cleanup-failure.txt", error)
                            if propagate is None:
                                propagate = BugFixLifecycleInfrastructureError(f"Agent session cleanup failed: {error}")

                    try:
                        full_patch = self._freeze_submission(
                            request.paths.agent_workspace,
                            trusted_source.commit,
                        )
                        submission_frozen = True
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

                if propagate is not None:
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
                self._persist_phase_results(phases)
                result = result.model_copy(update={"artifact_manifest": self._artifact_manifest(request)})
                try:
                    self._persist_result(request, result)
                    result_persisted = True
                except BaseException as persistence_error:  # noqa: BLE001 - cleanup still must run
                    persistence_error.add_note(f"Primary lifecycle failure: {propagate}")
                    propagate = persistence_error
        finally:
            cleanup_error = self._cleanup()

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

        sf: CheckpointManifest | None = None
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
    ) -> None:
        names = {
            "test_red": "test-red",
            "test_gold": "test-gold",
            "fix_build": "fix-build",
            "generated_pair": "generated-pair",
            "benchmark_fix": "benchmark-fix",
        }
        for field_name, evidence_name in names.items():
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
        resolution = result.metric_status(BugFixMetricName.RESOLUTION)
        return result.model_copy(
            update={
                "resolved": resolution is BugFixPhaseStatus.PASSED,
                "infrastructure_failure": resolution
                in (
                    BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
                    BugFixPhaseStatus.NOT_RUN,
                ),
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
        result.save(
            request.context.result_dir,
            f"{request.context.entry.instance_id}.jsonl",
        )
        self._evidence_store.save_final_result(result)

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

    def _cleanup(self) -> CleanupInfrastructureError | None:
        errors: list[str] = []
        container_absent = False
        try:
            self._ownership_api.verify_container_ownership()
        except Exception as error:  # noqa: BLE001 - cleanup aggregates every ownership failure
            errors.append(f"container ownership verification: {error}")
        else:
            for name, operation in (
                ("evaluator process stop", self._ownership_api.stop_evaluator_processes),
                ("BC user removal", self._ownership_api.remove_bc_user),
                ("container removal", self._ownership_api.remove_container_and_verify),
            ):
                try:
                    operation()
                except Exception as error:  # noqa: BLE001 - cleanup must continue to quarantine
                    errors.append(f"{name}: {error}")
                    break
            else:
                container_absent = True

        if container_absent:
            for name, operation in (
                ("ACL removal", self._ownership_api.remove_acl),
                ("local identity removal", self._ownership_api.remove_local_identity),
                ("managed root removal", self._ownership_api.remove_roots),
            ):
                try:
                    operation()
                except Exception as error:  # noqa: BLE001 - cleanup must continue to quarantine
                    errors.append(f"{name}: {error}")
                    break

        if not errors:
            return None
        try:
            self._ownership_api.quarantine(tuple(errors))
        except Exception as error:  # noqa: BLE001 - cleanup reports quarantine failure too
            errors.append(f"quarantine persistence: {error}")
        return CleanupInfrastructureError("; ".join(errors))


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


def _prerequisite_phase(
    prerequisite: BugFixPhaseResult,
    reason: str,
) -> BugFixPhaseResult:
    if prerequisite.status is BugFixPhaseStatus.INVALID_SUBMISSION:
        return make_invalid_submission_phase(reason)
    if prerequisite.status is BugFixPhaseStatus.FAILED:
        now = datetime.now(UTC)
        return BugFixPhaseResult(
            status=BugFixPhaseStatus.FAILED,
            started_at=now,
            completed_at=now,
            error_message=reason,
        )
    return make_not_run_phase(reason)


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


class PowerShellLifecycleOwnershipApi:
    def __init__(
        self,
        request: BugFixLifecycleRequest,
        evidence_store: EvidenceStore,
        powershell_runner: PowerShellRunner,
        *,
        module_path: Path | None = None,
    ) -> None:
        self._request = request
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
                    f"  -Username {_ps_quote(self._request.agent_bc_username)} `",
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
        encoded_paths = json.dumps([str(path) for path in self._request.acl_paths])
        self._invoke(
            "\n".join(
                (
                    "$ErrorActionPreference = 'Stop'",
                    f"Import-Module {_ps_quote(self._module_path)} -Force",
                    f"$paths = '{_ps_single_quote(encoded_paths)}' | ConvertFrom-Json",
                    "$transaction = [PSCustomObject]@{",
                    f"  Sid = {_ps_quote(self._request.agent_os_sid)}",
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
                    f"  -Username {_ps_quote(self._request.agent_os_username)}",
                )
            )
        )

    def remove_roots(self) -> None:
        if self._request.paths.entry_root.exists():
            remove_tree(self._request.paths.entry_root)

    def quarantine(self, errors: tuple[str, ...]) -> None:
        destination = self._request.paths.final_results / "cleanup-quarantine.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(
            destination,
            {
                "cleanup_errors": list(errors),
                "container_id": self._container_id,
                "container_invocation_id": self._invocation_id,
                "instance_id": self._request.context.entry.instance_id,
            },
        )

    @property
    def _container_name(self) -> str:
        return self._request.evaluator_container.name

    @property
    def _container_id(self) -> str:
        return self._request.expected_container_id

    @property
    def _invocation_id(self) -> str:
        return self._request.expected_container_invocation_id

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
    lifecycle = BugFixProductionLifecycle.from_request(
        request,
        powershell_runner=powershell_runner,
    )
    return lifecycle.run(request, agent_runner)


def _atomic_json(destination: Path, payload: object) -> None:
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
            json.dump(payload, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
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
