from __future__ import annotations

import json
import subprocess
import tempfile
import traceback
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from bcbench.dataset import TestEntry
from bcbench.evaluate.bugfix_lifecycle.checkpoint import CheckpointManager
from bcbench.evaluate.bugfix_lifecycle.evidence import EvidenceStore, sha256_file, sha256_text
from bcbench.evaluate.bugfix_lifecycle.inventory import (
    InventoryReader,
    InventoryVerifier,
    expected_inventory_after_publication,
)
from bcbench.evaluate.bugfix_lifecycle.models import (
    AppInventoryEntry,
    CheckpointManifest,
    ProjectPublication,
    TrustedSource,
)
from bcbench.evaluate.bugfix_lifecycle.workspace import TrustedWorkspaceBuilder, materialized_workspace_tree_hash
from bcbench.evaluate.bugfix_output import GeneratedBugFixOutput
from bcbench.exceptions import (
    BugFixLifecycleInfrastructureError,
    BuildError,
    BuildTimeoutExpired,
    CheckpointInfrastructureError,
    CleanupInfrastructureError,
    GeneratedSubmissionError,
    PackageInventoryError,
    PatchApplicationError,
    PhaseExecutionInfrastructureError,
    TestExecutionError,
    TestExecutionFailureKind,
    TestExecutionTimeoutExpired,
    TestInfrastructureError,
)
from bcbench.operations.bc_operations import (
    TestSuiteEvidence,
    build_and_publish_projects_with_evidence,
    run_test_suite_with_evidence,
)
from bcbench.operations.filesystem_operations import remove_tree
from bcbench.operations.git_operations import apply_patch
from bcbench.operations.project_operations import is_test_project, order_project_paths
from bcbench.operations.test_execution import TestExpectation, TestIdentity, TestOutcome, TestRunSummary
from bcbench.results.bugfix import BugFixPhaseResult, BugFixPhaseStatus
from bcbench.types import ContainerConfig

PatchApplier = Callable[[Path, str, str], None]
WorkspaceCleaner = Callable[[Path], None]
WorkspaceHasher = Callable[[Path], str]


class ProjectPublisher(Protocol):
    def build_and_publish(
        self,
        repo_path: Path,
        project_paths: tuple[str, ...],
    ) -> tuple[Path, ...]: ...


class EvidenceProjectPublisher(ProjectPublisher, Protocol):
    def build_and_publish_with_evidence(
        self,
        repo_path: Path,
        project_paths: tuple[str, ...],
        evidence_directory: Path,
    ) -> ProjectPublication: ...


class ExactTestRunner(Protocol):
    def run(
        self,
        tests: tuple[TestEntry, ...],
        expectation: TestExpectation,
        repo_path: Path,
    ) -> TestRunSummary: ...


class EvidenceExactTestRunner(ExactTestRunner, Protocol):
    def run_with_evidence(
        self,
        tests: tuple[TestEntry, ...],
        expectation: TestExpectation,
        repo_path: Path,
        evidence_directory: Path,
    ) -> TestSuiteEvidence: ...


class DefaultProjectPublisher:
    def __init__(self, container: ContainerConfig, version: str) -> None:
        self._container = container
        self._version = version

    def build_and_publish(
        self,
        repo_path: Path,
        project_paths: tuple[str, ...],
    ) -> tuple[Path, ...]:
        with tempfile.TemporaryDirectory(prefix=".bcbench-publication-evidence-", dir=repo_path) as evidence_directory:
            return self.build_and_publish_with_evidence(
                repo_path,
                project_paths,
                Path(evidence_directory),
            ).package_paths

    def build_and_publish_with_evidence(
        self,
        repo_path: Path,
        project_paths: tuple[str, ...],
        evidence_directory: Path,
    ) -> ProjectPublication:
        evidence_directory.mkdir(parents=True, exist_ok=True)
        publication = build_and_publish_projects_with_evidence(
            repo_path,
            list(project_paths),
            self._container,
            self._version,
            evidence_directory,
        )
        return ProjectPublication(
            project_paths=project_paths,
            package_paths=publication.package_paths,
            apps=tuple(
                _app_inventory_from_package(
                    repo_path / record.project_path,
                    record.package_path,
                )
                for record in publication.projects
            ),
            evidence_paths=tuple(
                path
                for record in publication.projects
                for path in (
                    record.command_path,
                    record.stdout_path,
                    record.stderr_path,
                    record.diagnostics_path,
                )
            ),
        )


class DefaultExactTestRunner:
    def __init__(self, container: ContainerConfig) -> None:
        self._container = container

    def run(
        self,
        tests: tuple[TestEntry, ...],
        expectation: TestExpectation,
        repo_path: Path,
    ) -> TestRunSummary:
        with tempfile.TemporaryDirectory(prefix=".bcbench-test-evidence-", dir=repo_path) as evidence_directory:
            return self.run_with_evidence(
                tests,
                expectation,
                repo_path,
                Path(evidence_directory),
            ).summary

    def run_with_evidence(
        self,
        tests: tuple[TestEntry, ...],
        expectation: TestExpectation,
        repo_path: Path,
        evidence_directory: Path,
    ) -> TestSuiteEvidence:
        evidence_directory.mkdir(parents=True, exist_ok=True)
        evidence = run_test_suite_with_evidence(
            list(tests),
            expectation,
            self._container,
            repo_path,
            evidence_directory,
        )
        _require_exact_test_summary(evidence.summary, tests, expectation)
        return evidence


@dataclass
class _PhaseState:
    name: str
    source_description: str
    submission: GeneratedBugFixOutput
    trusted_source_commit: str
    container_id: str
    image_id: str
    hostname: str
    mounts: tuple[str, ...]
    checkpoint_hash: str | None
    generated_fix_patch_hash: str | None = None
    generated_test_patch_hash: str | None = None
    gold_patch_hash: str | None = None
    benchmark_patch_hash: str | None = None
    trusted_patches: tuple[tuple[str, str, str], ...] = ()
    trusted_source_hash: str | None = None
    materialized_source_hash: str | None = None
    prebuild_source_hashes: list[str] = field(default_factory=list)
    workspace: Path | None = None
    packages: list[Path] = field(default_factory=list)
    package_hashes: dict[Path, str] = field(default_factory=dict)
    protected_kinds: dict[Path, str] = field(default_factory=dict)
    summary: TestRunSummary | None = None
    evidence: dict[str, str] = field(default_factory=dict)
    evidence_sources: dict[str, Path] = field(default_factory=dict)
    additional_sources: dict[str, str] = field(default_factory=dict)
    raw_evidence_roots: list[Path] = field(default_factory=list)
    protected_packages: set[Path] = field(default_factory=set)
    secondary_diagnostics: list[str] = field(default_factory=list)
    expected_apps: tuple[AppInventoryEntry, ...] = ()
    operation_index: int = 0
    inventory_index: int = 0


def make_not_run_phase(reason: str) -> BugFixPhaseResult:
    now = datetime.now(UTC)
    return BugFixPhaseResult(
        status=BugFixPhaseStatus.NOT_RUN,
        started_at=now,
        completed_at=now,
        error_message=reason,
    )


def classify_phase_error(error: BaseException) -> BugFixPhaseStatus | None:
    if isinstance(error, GeneratedSubmissionError):
        return BugFixPhaseStatus.INVALID_SUBMISSION
    if isinstance(error, TestExecutionError):
        if error.failure_kind is TestExecutionFailureKind.SELECTION_EVIDENCE:
            return BugFixPhaseStatus.INFRASTRUCTURE_ERROR
        return BugFixPhaseStatus.FAILED
    if isinstance(error, BuildError):
        return BugFixPhaseStatus.FAILED
    if isinstance(
        error,
        (
            BuildTimeoutExpired,
            CheckpointInfrastructureError,
            TestExecutionTimeoutExpired,
            TestInfrastructureError,
            BugFixLifecycleInfrastructureError,
        ),
    ):
        return BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    return None


def make_invalid_submission_phase(reason: str) -> BugFixPhaseResult:
    now = datetime.now(UTC)
    return BugFixPhaseResult(
        status=BugFixPhaseStatus.INVALID_SUBMISSION,
        started_at=now,
        completed_at=now,
        error_message=reason,
    )


not_run_phase = make_not_run_phase
invalid_submission_phase = make_invalid_submission_phase


class BugFixPhaseRunner:
    def __init__(
        self,
        *,
        trusted_source: TrustedSource,
        workspace_builder: TrustedWorkspaceBuilder,
        checkpoint_manager: CheckpointManager,
        evidence_store: EvidenceStore,
        container: ContainerConfig,
        version: str,
        project_paths: Sequence[str] = (),
        publisher: ProjectPublisher | EvidenceProjectPublisher | None = None,
        test_runner: ExactTestRunner | EvidenceExactTestRunner | None = None,
        patch_applier: PatchApplier = apply_patch,
        workspace_cleaner: WorkspaceCleaner = remove_tree,
        workspace_hasher: WorkspaceHasher = materialized_workspace_tree_hash,
        inventory_reader: InventoryReader | None = None,
        inventory_verifier: InventoryVerifier | None = None,
    ) -> None:
        if evidence_store is None:
            raise ValueError("An evidence store is required")
        if inventory_verifier is None and inventory_reader is None:
            raise ValueError("An inventory verifier or inventory reader is required")
        if inventory_verifier is not None and inventory_reader is not None:
            raise ValueError("Provide either inventory_verifier or inventory_reader, not both")
        self._trusted_source = trusted_source
        self._workspace_builder = workspace_builder
        self._checkpoint_manager = checkpoint_manager
        self._evidence_store = evidence_store
        self._container = container
        self._version = version
        self._project_paths = tuple(project_paths)
        self._publisher = publisher or DefaultProjectPublisher(container, version)
        self._test_runner = test_runner or DefaultExactTestRunner(container)
        self._patch_applier = patch_applier
        self._workspace_cleaner = workspace_cleaner
        self._workspace_hasher = workspace_hasher
        if inventory_verifier is not None:
            self._inventory_verifier = inventory_verifier
        else:
            if inventory_reader is None:
                raise ValueError("An inventory reader is required")
            self._inventory_verifier = InventoryVerifier(inventory_reader, evidence_store)
        self._generated_test_package_hashes: set[str] = set()

    def run_test_red(
        self,
        submission: GeneratedBugFixOutput,
        s0: CheckpointManifest,
    ) -> BugFixPhaseResult:
        source_description = self._source_description(generated_test_patch=submission.test_patch)

        def action(state: _PhaseState) -> None:
            self._restore_and_verify(state, s0)
            self._require_single_generated_test(submission)
            self._create_phase_workspace(state)
            self._apply_generated(
                state,
                submission.test_patch,
                submission.test_patch_hash,
                "test-red generated test patch",
            )
            self._capture_materialized_source(state)
            self._publish_batch(
                state,
                self._product_projects(submission),
                "test-red-product",
                trusted=True,
            )
            test_packages = self._publish_batch(
                state,
                submission.test_projects,
                "generated-test",
                trusted=False,
            )
            self._generated_test_package_hashes.update(sha256_file(package) for package in test_packages)
            self._verify_no_unexpected_workspace_packages(state)
            state.summary = self._run_exact_tests(
                state,
                submission.tests,
                TestExpectation.ALL_FAIL,
                state.workspace,
            )

        return self._execute_phase(
            "test-red",
            s0,
            source_description,
            submission,
            action,
            generated_test_patch_hash=submission.test_patch_hash,
        )

    def run_test_gold(
        self,
        submission: GeneratedBugFixOutput,
        s0: CheckpointManifest,
        gold_patch: str,
    ) -> BugFixPhaseResult:
        gold_patch_hash = sha256_text(gold_patch)
        source_description = self._source_description(
            trusted_gold_patch=gold_patch,
            generated_test_patch=submission.test_patch,
        )
        product_source_description = self._source_description(
            trusted_gold_patch=gold_patch,
        )

        def action(state: _PhaseState) -> None:
            self._restore_and_verify(state, s0)
            self._require_single_generated_test(submission)
            self._create_phase_workspace(state)
            self._apply_trusted(
                state,
                gold_patch,
                gold_patch_hash,
                "test-gold trusted gold patch",
            )
            state.additional_sources["gold_product_source"] = product_source_description
            self._capture_materialized_source(state)
            product_source_hash = state.materialized_source_hash
            if product_source_hash is None:
                raise BugFixLifecycleInfrastructureError("Gold product source hash was not captured")
            product_packages = self._publish_batch(
                state,
                self._product_projects(submission),
                f"gold-product-{product_source_hash}",
                trusted=True,
            )
            self._protect_packages(
                state,
                product_packages,
                f"gold-product-{product_source_hash}",
            )
            self._apply_generated(
                state,
                submission.test_patch,
                submission.test_patch_hash,
                "test-gold generated test patch",
            )
            self._capture_materialized_source(state)
            test_packages = self._publish_batch(
                state,
                submission.test_projects,
                "generated-test",
                trusted=False,
            )
            self._generated_test_package_hashes.update(sha256_file(package) for package in test_packages)
            self._verify_no_unexpected_workspace_packages(state)
            state.summary = self._run_exact_tests(
                state,
                submission.tests,
                TestExpectation.ALL_PASS,
                state.workspace,
            )

        return self._execute_phase(
            "test-gold",
            s0,
            source_description,
            submission,
            action,
            generated_test_patch_hash=submission.test_patch_hash,
            gold_patch=(gold_patch, gold_patch_hash),
        )

    def run_fix_build(
        self,
        submission: GeneratedBugFixOutput,
        s0: CheckpointManifest,
    ) -> tuple[BugFixPhaseResult, CheckpointManifest | None]:
        source_description = self._source_description(generated_fix_patch=submission.fix_patch)
        fixed_manifest: CheckpointManifest | None = None

        def action(state: _PhaseState) -> None:
            nonlocal fixed_manifest
            self._restore_and_verify(state, s0)
            self._create_phase_workspace(state)
            self._apply_generated(
                state,
                submission.fix_patch,
                submission.fix_patch_hash,
                "fix-build generated fix patch",
            )
            self._capture_materialized_source(state)
            self._assert_projects_have_no_packages(
                state.workspace,
                submission.test_projects,
                "generated test",
            )
            self._publish_batch(
                state,
                self._product_projects(submission),
                "fixed-product",
                trusted=False,
            )
            self._verify_no_unexpected_workspace_packages(state)
            self._assert_no_forbidden_package_hashes(state.workspace)
            fixed_manifest = self._checkpoint_manager.capture(
                "fixed",
                state.expected_apps,
            )
            state.checkpoint_hash = fixed_manifest.sha256
            state.evidence["fixed_checkpoint"] = self._relative_protected_path(fixed_manifest.backup_path)

        result = self._execute_phase(
            "fix-build",
            s0,
            source_description,
            submission,
            action,
            generated_fix_patch_hash=submission.fix_patch_hash,
        )
        if result.status is not BugFixPhaseStatus.PASSED:
            fixed_manifest = None
        return result, fixed_manifest

    def run_generated_pair(
        self,
        submission: GeneratedBugFixOutput,
        sf: CheckpointManifest | None,
        red_result: BugFixPhaseResult,
    ) -> BugFixPhaseResult:
        if sf is None:
            return self._persist_dependency_result(
                "generated-pair",
                make_not_run_phase("Fixed checkpoint is unavailable."),
            )

        expected_identity = _canonical_test_entries(submission.tests)
        if not red_result.executed_tests:
            return self._persist_dependency_result(
                "generated-pair",
                make_not_run_phase("The red phase did not execute the generated test."),
            )
        if Counter(red_result.executed_tests) != Counter(expected_identity):
            return self._persist_dependency_result(
                "generated-pair",
                make_not_run_phase("The red phase did not execute the exact generated test identity."),
            )

        source_description = self._source_description(
            generated_fix_patch=submission.fix_patch,
            generated_test_patch=submission.test_patch,
        )

        def action(state: _PhaseState) -> None:
            self._verify_checkpoint_inventory(state, sf)
            self._require_single_generated_test(submission)
            self._create_phase_workspace(state)
            self._apply_generated(
                state,
                submission.fix_patch,
                submission.fix_patch_hash,
                "generated-pair generated fix patch",
            )
            self._apply_generated(
                state,
                submission.test_patch,
                submission.test_patch_hash,
                "generated-pair generated test patch",
            )
            self._capture_materialized_source(state)
            test_packages = self._publish_batch(
                state,
                submission.test_projects,
                "generated-test",
                trusted=False,
            )
            self._generated_test_package_hashes.update(sha256_file(package) for package in test_packages)
            self._verify_no_unexpected_workspace_packages(state)
            state.summary = self._run_exact_tests(
                state,
                submission.tests,
                TestExpectation.ALL_PASS,
                state.workspace,
            )

        return self._execute_phase(
            "generated-pair",
            sf,
            source_description,
            submission,
            action,
            generated_fix_patch_hash=submission.fix_patch_hash,
            generated_test_patch_hash=submission.test_patch_hash,
        )

    def run_benchmark_fix(
        self,
        submission: GeneratedBugFixOutput,
        sf: CheckpointManifest,
        benchmark_patch: str,
        benchmark_tests: tuple[TestEntry, ...],
    ) -> BugFixPhaseResult:
        benchmark_patch_hash = sha256_text(benchmark_patch)
        source_description = self._source_description(
            generated_fix_patch=submission.fix_patch,
            trusted_benchmark_patch=benchmark_patch,
        )

        def action(state: _PhaseState) -> None:
            self._restore_and_verify(state, sf)
            self._create_phase_workspace(state)
            self._assert_projects_have_no_packages(
                state.workspace,
                submission.test_projects,
                "generated test",
            )
            self._apply_generated(
                state,
                submission.fix_patch,
                submission.fix_patch_hash,
                "benchmark-fix generated fix patch",
            )
            self._apply_trusted(
                state,
                benchmark_patch,
                benchmark_patch_hash,
                "benchmark-fix trusted benchmark patch",
            )
            self._capture_materialized_source(state)
            self._assert_projects_have_no_packages(
                state.workspace,
                submission.test_projects,
                "generated test",
            )
            self._publish_batch(
                state,
                self._benchmark_test_projects(),
                "benchmark-test",
                trusted=True,
            )
            self._verify_no_unexpected_workspace_packages(state)
            self._assert_no_forbidden_package_hashes(state.workspace)
            state.summary = self._run_exact_tests(
                state,
                benchmark_tests,
                TestExpectation.ALL_PASS,
                state.workspace,
            )

        return self._execute_phase(
            "benchmark-fix",
            sf,
            source_description,
            submission,
            action,
            generated_fix_patch_hash=submission.fix_patch_hash,
            benchmark_patch=(benchmark_patch, benchmark_patch_hash),
        )

    def _execute_phase(
        self,
        name: str,
        checkpoint: CheckpointManifest,
        source_description: str,
        submission: GeneratedBugFixOutput,
        action: Callable[[_PhaseState], None],
        *,
        generated_fix_patch_hash: str | None = None,
        generated_test_patch_hash: str | None = None,
        gold_patch: tuple[str, str] | None = None,
        benchmark_patch: tuple[str, str] | None = None,
    ) -> BugFixPhaseResult:
        started_at = datetime.now(UTC)
        state = _PhaseState(
            name=name,
            source_description=source_description,
            submission=submission,
            trusted_source_commit=self._trusted_source.commit,
            container_id=checkpoint.container.container_id,
            image_id=checkpoint.container.image_id,
            hostname=checkpoint.container.hostname,
            mounts=checkpoint.container.mounts,
            checkpoint_hash=checkpoint.sha256,
            generated_fix_patch_hash=generated_fix_patch_hash,
            generated_test_patch_hash=generated_test_patch_hash,
            gold_patch_hash=gold_patch[1] if gold_patch is not None else None,
            benchmark_patch_hash=benchmark_patch[1] if benchmark_patch is not None else None,
            trusted_patches=tuple(
                patch
                for patch in (
                    ("gold patch", *gold_patch) if gold_patch is not None else None,
                    ("benchmark patch", *benchmark_patch) if benchmark_patch is not None else None,
                )
                if patch is not None
            ),
            expected_apps=checkpoint.apps,
        )
        status = BugFixPhaseStatus.PASSED
        error_message: str | None = None
        unexpected_error: BaseException | None = None

        try:
            action(state)
        except BaseException as error:  # noqa: BLE001 - cleanup and evidence must survive interrupts
            self._capture_error_summary(state, error)
            mapped_status = self._map_error_status(error)
            if mapped_status is None:
                unexpected_error = error
                status = BugFixPhaseStatus.INFRASTRUCTURE_ERROR
                error_message = str(error)
                self._save_emergency_diagnostic(state, error)
            else:
                status = mapped_status
                error_message = str(error)

        try:
            self._persist_phase_artifacts(state)
        except BaseException as error:  # noqa: BLE001 - cleanup must still run
            if unexpected_error is None:
                status = BugFixPhaseStatus.INFRASTRUCTURE_ERROR
                error_message = f"Phase evidence or package protection failed: {error}"
            else:
                self._save_secondary_diagnostic(state, "artifact", error)

        cleanup_error = self._cleanup_workspace(state.workspace)
        if cleanup_error is not None:
            if unexpected_error is None:
                status = BugFixPhaseStatus.INFRASTRUCTURE_ERROR
                error_message = str(cleanup_error)
            self._save_secondary_diagnostic(state, "cleanup", cleanup_error)

        result = self._phase_result(
            state,
            status=status,
            started_at=started_at,
            error_message=error_message,
        )
        self._evidence_store.save_phase(name, result)
        if unexpected_error is not None:
            raise PhaseExecutionInfrastructureError(
                unexpected_error,
                result,
                name,
            ) from unexpected_error
        return result

    def _restore(self, manifest: CheckpointManifest) -> None:
        self._checkpoint_manager.restore(manifest, manifest.apps)

    def _restore_and_verify(
        self,
        state: _PhaseState,
        manifest: CheckpointManifest,
    ) -> None:
        self._restore(manifest)
        self._verify_checkpoint_inventory(state, manifest)

    def _verify_checkpoint_inventory(
        self,
        state: _PhaseState,
        manifest: CheckpointManifest,
    ) -> None:
        state.expected_apps = manifest.apps
        self._verify_runtime_inventory(state, "checkpoint")

    def _create_workspace(self, name: str) -> Path:
        try:
            return self._workspace_builder.create_evaluator_workspace(
                self._trusted_source,
                name,
            )
        except (OSError, ValueError) as error:
            raise BugFixLifecycleInfrastructureError(f"Failed to create evaluator workspace for {name}: {error}") from error

    def _create_phase_workspace(self, state: _PhaseState) -> None:
        self._verify_phase_patch_hashes(state)
        state.workspace = self._create_workspace(state.name)
        state.trusted_source_hash = self._hash_workspace(state.workspace)

    def _hash_workspace(self, workspace: Path) -> str:
        try:
            tree_hash = self._workspace_hasher(workspace)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise BugFixLifecycleInfrastructureError(f"Failed to hash evaluator workspace tree: {error}") from error
        if not tree_hash:
            raise BugFixLifecycleInfrastructureError("Evaluator workspace tree hash is empty")
        return tree_hash

    def _capture_materialized_source(self, state: _PhaseState) -> None:
        if state.workspace is None:
            raise BugFixLifecycleInfrastructureError("Evaluator workspace is unavailable")
        self._verify_phase_patch_hashes(state)
        state.materialized_source_hash = self._hash_workspace(state.workspace)

    def _verify_materialized_source(self, state: _PhaseState) -> None:
        if state.workspace is None or state.materialized_source_hash is None:
            raise BugFixLifecycleInfrastructureError("Expected evaluator source state has not been captured")
        self._verify_phase_patch_hashes(state)
        actual_hash = self._hash_workspace(state.workspace)
        state.prebuild_source_hashes.append(actual_hash)
        if actual_hash != state.materialized_source_hash:
            raise BugFixLifecycleInfrastructureError(f"Evaluator workspace tree hash mismatch before build: expected {state.materialized_source_hash}, got {actual_hash}")

    def _verify_phase_patch_hashes(self, state: _PhaseState) -> None:
        generated_patches = (
            ("generated full patch", state.submission.full_patch, state.submission.full_patch_hash),
            ("generated fix patch", state.submission.fix_patch, state.submission.fix_patch_hash),
            ("generated test patch", state.submission.test_patch, state.submission.test_patch_hash),
        )
        for label, patch, expected_hash in generated_patches:
            self._verify_patch_hash(patch, expected_hash, label, generated=True)
        for label, patch, expected_hash in state.trusted_patches:
            self._verify_patch_hash(patch, expected_hash, label, generated=False)

    def _verify_patch_hash(
        self,
        patch: str,
        expected_hash: str,
        label: str,
        *,
        generated: bool,
    ) -> None:
        actual_hash = sha256_text(patch)
        if actual_hash == expected_hash:
            return
        message = f"{label} SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
        if generated:
            raise GeneratedSubmissionError(message)
        raise BugFixLifecycleInfrastructureError(message)

    def _apply_generated(
        self,
        state: _PhaseState,
        patch: str,
        expected_hash: str,
        patch_name: str,
    ) -> None:
        if state.workspace is None:
            raise BugFixLifecycleInfrastructureError("Evaluator workspace is unavailable")
        self._verify_patch_hash(patch, expected_hash, patch_name, generated=True)
        try:
            self._patch_applier(state.workspace, patch, patch_name)
        except PatchApplicationError as error:
            raise GeneratedSubmissionError(str(error)) from error

    def _apply_trusted(
        self,
        state: _PhaseState,
        patch: str,
        expected_hash: str,
        patch_name: str,
    ) -> None:
        if state.workspace is None:
            raise BugFixLifecycleInfrastructureError("Evaluator workspace is unavailable")
        self._verify_patch_hash(patch, expected_hash, patch_name, generated=False)
        try:
            self._patch_applier(state.workspace, patch, patch_name)
        except PatchApplicationError as error:
            raise BugFixLifecycleInfrastructureError(f"Trusted patch application failed: {error}") from error

    def _publish_batch(
        self,
        state: _PhaseState,
        project_paths: Sequence[str],
        protected_kind: str,
        *,
        trusted: bool,
    ) -> tuple[Path, ...]:
        if not project_paths:
            return ()
        if state.workspace is None:
            raise BugFixLifecycleInfrastructureError("Evaluator workspace is unavailable")
        evidence_directory = self._operation_evidence_directory(state, "publication")
        self._verify_materialized_source(state)
        try:
            requested_projects = tuple(project_paths)
            publish_with_evidence = getattr(self._publisher, "build_and_publish_with_evidence", None)
            if publish_with_evidence is not None:
                returned = publish_with_evidence(
                    state.workspace,
                    requested_projects,
                    evidence_directory,
                )
            else:
                build_and_publish = getattr(self._publisher, "build_and_publish", None)
                if build_and_publish is not None:
                    package_paths = build_and_publish(state.workspace, requested_projects)
                    returned = ProjectPublication(
                        project_paths=requested_projects,
                        package_paths=tuple(package_paths),
                    )
                else:
                    legacy_publish = getattr(self._publisher, "publish", self._publisher)
                    returned = legacy_publish(
                        state.workspace,
                        requested_projects,
                        self._container,
                        self._version,
                        evidence_directory,
                    )
        except BuildError as error:
            if trusted:
                raise BugFixLifecycleInfrastructureError(f"Trusted project publication failed: {error}") from error
            raise
        except BuildTimeoutExpired:
            raise
        except (OSError, ValueError) as error:
            raise PackageInventoryError(f"Project publication infrastructure failed: {error}") from error
        if not isinstance(returned, ProjectPublication):
            raise PackageInventoryError("Project publisher must return typed publication evidence")
        publication = ProjectPublication(
            project_paths=returned.project_paths,
            package_paths=tuple(package if package.is_absolute() else state.workspace / package for package in returned.package_paths),
            apps=returned.apps,
            evidence_paths=returned.evidence_paths,
        )
        if publication.project_paths != tuple(project_paths):
            raise PackageInventoryError(f"Project publication paths do not match the request: expected={tuple(project_paths)}, actual={publication.project_paths}")
        self._verify_publication(
            state,
            publication,
            allow_generated_test=protected_kind == "generated-test",
        )
        published_apps = publication.apps or self._publication_apps(state, publication)
        state.packages.extend(publication.package_paths)
        state.package_hashes.update((package.resolve(), sha256_file(package)) for package in publication.package_paths)
        state.protected_kinds.update(dict.fromkeys(publication.package_paths, protected_kind))
        for path in publication.evidence_paths:
            state.evidence_sources[f"raw_{len(state.evidence_sources):03d}_{path.name}"] = path
        state.expected_apps = expected_inventory_after_publication(state.expected_apps, published_apps)
        self._verify_runtime_inventory(state, "post-publication")
        return publication.package_paths

    def _verify_publication(
        self,
        state: _PhaseState,
        publication: ProjectPublication,
        *,
        allow_generated_test: bool,
    ) -> None:
        if state.workspace is None:
            raise PackageInventoryError("Evaluator workspace is unavailable")
        if not publication.package_paths:
            raise PackageInventoryError(f"No application packages were returned for {publication.project_paths}")

        workspace = state.workspace.resolve()
        packages = tuple(path.resolve() for path in publication.package_paths)
        if len(set(packages)) != len(packages):
            raise PackageInventoryError("Project publication returned duplicate package paths")

        project_roots = {project: (workspace / Path(project.replace("\\", "/"))).resolve() for project in publication.project_paths}
        for package in packages:
            if not package.is_file() or package.is_symlink():
                raise PackageInventoryError(f"Published package is not a regular file: {package}")
            if not package.is_relative_to(workspace):
                raise PackageInventoryError(f"Published package is outside evaluator workspace: {package}")
            if ".alpackages" in {part.casefold() for part in package.parts}:
                raise PackageInventoryError(f"Dependency package was reported as generated output: {package}")
            if not any(package.is_relative_to(root) for root in project_roots.values()):
                raise PackageInventoryError(f"Published package is outside requested projects: {package}")

        missing_projects = [project for project, root in project_roots.items() if not any(package.is_relative_to(root) for package in packages)]
        if missing_projects:
            raise PackageInventoryError(f"Projects produced no application package: {missing_projects}")
        package_counts = {project: sum(package.is_relative_to(root) for package in packages) for project, root in project_roots.items()}
        invalid_counts = {project: count for project, count in package_counts.items() if count != 1}
        if invalid_counts:
            raise PackageInventoryError(f"Projects must produce exactly one application package: {invalid_counts}")
        if publication.apps:
            package_hashes = Counter(sha256_file(package) for package in packages)
            app_hashes = Counter(app.content_hash for app in publication.apps)
            if None in app_hashes or app_hashes != package_hashes:
                raise PackageInventoryError(f"Publication application hashes do not match package hashes: apps={app_hashes}, packages={package_hashes}")

        if not allow_generated_test:
            forbidden = self._generated_test_package_hashes
            contaminated = sorted(str(package) for package in packages if sha256_file(package) in forbidden)
            if contaminated:
                raise PackageInventoryError(f"Generated test packages are forbidden in this phase: {contaminated}")

    def _publication_apps(
        self,
        state: _PhaseState,
        publication: ProjectPublication,
    ) -> tuple[AppInventoryEntry, ...]:
        if state.workspace is None:
            raise PackageInventoryError("Evaluator workspace is unavailable")
        apps: list[AppInventoryEntry] = []
        for project in publication.project_paths:
            project_root = state.workspace / Path(project.replace("\\", "/"))
            project_packages = tuple(package for package in publication.package_paths if package.resolve().is_relative_to(project_root.resolve()))
            if len(project_packages) != 1:
                raise PackageInventoryError(f"Expected exactly one package for project {project!r}, found {len(project_packages)}")
            apps.append(_app_inventory_from_package(project_root, project_packages[0]))
        return tuple(apps)

    def _operation_evidence_directory(
        self,
        state: _PhaseState,
        operation: str,
    ) -> Path:
        if state.workspace is None:
            raise BugFixLifecycleInfrastructureError("Evaluator workspace is unavailable")
        path = state.workspace / "evidence" / state.name / f"{state.operation_index:02d}-{operation}"
        state.operation_index += 1
        state.raw_evidence_roots.append(path)
        return path

    def _verify_runtime_inventory(
        self,
        state: _PhaseState,
        stage: str,
    ) -> None:
        evidence_name = f"{state.name}-{state.inventory_index:02d}-{stage}"
        try:
            inventory, path = self._inventory_verifier.verify(
                evidence_name,
                state.expected_apps,
            )
        except PackageInventoryError:
            path = self._inventory_verifier.last_evidence_path
            if path is not None:
                state.evidence_sources[f"inventory_{state.inventory_index + 1:02d}"] = path
            raise
        state.inventory_index += 1
        state.expected_apps = inventory
        state.evidence_sources[f"inventory_{state.inventory_index:02d}"] = path

    def _run_exact_tests(
        self,
        state: _PhaseState,
        tests: Sequence[TestEntry],
        expectation: TestExpectation,
        workspace: Path,
    ) -> TestRunSummary:
        evidence_directory = self._operation_evidence_directory(state, "tests")
        try:
            requested_tests = tuple(tests)
            run_with_evidence = getattr(self._test_runner, "run_with_evidence", None)
            if run_with_evidence is not None:
                returned = run_with_evidence(
                    requested_tests,
                    expectation,
                    workspace,
                    evidence_directory,
                )
            else:
                run = getattr(self._test_runner, "run", None)
                returned = (
                    run(requested_tests, expectation, workspace)
                    if run is not None
                    else self._test_runner(
                        requested_tests,
                        expectation,
                        self._container,
                        workspace,
                        evidence_directory,
                    )
                )
        except (OSError, ValueError, ET.ParseError) as error:
            raise BugFixLifecycleInfrastructureError(f"Invalid exact test evidence: {error}") from error
        if isinstance(returned, TestSuiteEvidence):
            summary = returned.summary
            for path in (
                returned.command_path,
                returned.stdout_path,
                returned.stderr_path,
                *returned.discovery_paths,
                *returned.junit_paths,
            ):
                state.evidence_sources[f"raw_{len(state.evidence_sources):03d}_{path.name}"] = path
        elif isinstance(returned, TestRunSummary):
            summary = returned
        else:
            raise BugFixLifecycleInfrastructureError("Exact test runner must return a test summary or typed test evidence")
        _require_exact_test_summary(summary, tests, expectation)
        return summary

    def _persist_phase_artifacts(self, state: _PhaseState) -> None:
        source_path = self._evidence_store.save_submission(
            f"{state.name}-source.txt",
            state.source_description,
        )
        state.evidence_sources["source"] = source_path
        for key, content in state.additional_sources.items():
            state.evidence_sources[key] = self._evidence_store.save_submission(
                f"{state.name}-{key.replace('_', '-')}.txt",
                content,
            )
        state.evidence_sources["provenance"] = self._evidence_store.save_text(
            f"{state.name}-provenance.json",
            json.dumps(
                {
                    "benchmark_patch_hash": state.benchmark_patch_hash,
                    "checkpoint_hash": state.checkpoint_hash,
                    "container_id": state.container_id,
                    "generated_fix_patch_hash": state.generated_fix_patch_hash,
                    "generated_full_patch_hash": state.submission.full_patch_hash,
                    "generated_test_patch_hash": state.generated_test_patch_hash,
                    "gold_patch_hash": state.gold_patch_hash,
                    "hostname": state.hostname,
                    "image_id": state.image_id,
                    "materialized_source_hash": state.materialized_source_hash,
                    "mounts": list(state.mounts),
                    "prebuild_source_hashes": state.prebuild_source_hashes,
                    "trusted_source_commit": state.trusted_source_commit,
                    "trusted_source_hash": state.trusted_source_hash,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )

        for root in state.raw_evidence_roots:
            if root.is_dir():
                for path in sorted(
                    (candidate for candidate in root.rglob("*") if candidate.is_file()),
                    key=lambda candidate: str(candidate).casefold(),
                ):
                    state.evidence_sources.setdefault(
                        f"raw_{len(state.evidence_sources):03d}_{path.name}",
                        path,
                    )

        discovered_packages = (
            tuple(package for package in state.workspace.rglob("*.app") if ".alpackages" not in {part.casefold() for part in package.parts})
            if state.workspace is not None and state.workspace.is_dir()
            else ()
        )
        unique_packages = tuple(
            sorted(
                {package.resolve() for package in (*state.packages, *discovered_packages) if package.is_file()},
                key=lambda path: str(path).casefold(),
            )
        )
        for package in unique_packages:
            if package not in state.protected_packages:
                kind = state.protected_kinds.get(package, state.name)
                self._protect_packages(state, (package,), kind)

        if state.summary is not None:
            tests_path = self._evidence_store.save_text(
                f"{state.name}-tests.json",
                json.dumps(
                    {
                        "requested": _canonical_identities(state.summary.requested),
                        "discovered": _canonical_identities(state.summary.discovered),
                        "executed": _canonical_identities(state.summary.executed),
                        "outcomes": [result.outcome.value for result in state.summary.results],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            state.evidence_sources["tests"] = tests_path

        for key, path in tuple(state.evidence_sources.items()):
            if key in state.evidence:
                continue
            protected = self._evidence_store.protect_artifact(
                path,
                f"{state.name}-evidence",
            )
            state.evidence[key] = self._relative_protected_path(protected)

    def _protect_packages(
        self,
        state: _PhaseState,
        packages: Sequence[Path],
        kind: str,
    ) -> None:
        for package in packages:
            resolved = package.resolve()
            state.package_hashes[resolved] = sha256_file(resolved)
            protected = self._evidence_store.protect_artifact(resolved, kind)
            state.protected_packages.add(resolved)
            state.evidence[f"package_{len(state.protected_packages) - 1}"] = self._relative_protected_path(protected)

    def _relative_protected_path(self, path: Path) -> str:
        relative = getattr(self._evidence_store, "relative_protected_path", None)
        return str(relative(path) if relative is not None else path)

    def _cleanup_workspace(
        self,
        workspace: Path | None,
    ) -> CleanupInfrastructureError | None:
        if workspace is None:
            return None
        try:
            self._workspace_cleaner(workspace)
        except BaseException as error:  # noqa: BLE001 - cleanup interrupts become evidence
            return CleanupInfrastructureError(f"Evaluator workspace cleanup failed for {workspace}: {error}")
        return None

    def _phase_result(
        self,
        state: _PhaseState,
        *,
        status: BugFixPhaseStatus,
        started_at: datetime,
        error_message: str | None,
    ) -> BugFixPhaseResult:
        summary = state.summary
        if state.secondary_diagnostics:
            diagnostic_message = "; ".join(state.secondary_diagnostics)
            error_message = f"{error_message}\nSecondary evidence failures: {diagnostic_message}" if error_message else f"Secondary evidence failures: {diagnostic_message}"
        return BugFixPhaseResult(
            status=status,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            error_message=error_message,
            source_hash=state.materialized_source_hash,
            materialized_source_hash=state.materialized_source_hash,
            trusted_source_commit=state.trusted_source_commit,
            trusted_source_hash=state.trusted_source_hash,
            generated_fix_patch_hash=state.generated_fix_patch_hash,
            generated_test_patch_hash=state.generated_test_patch_hash,
            gold_patch_hash=state.gold_patch_hash,
            benchmark_patch_hash=state.benchmark_patch_hash,
            container_id=state.container_id,
            image_id=state.image_id,
            hostname=state.hostname,
            mounts=state.mounts,
            checkpoint_hash=state.checkpoint_hash,
            package_hashes=tuple(sorted(state.package_hashes.values())),
            requested_tests=(_canonical_identities(summary.requested) if summary is not None else ()),
            discovered_tests=(_canonical_identities(summary.discovered) if summary is not None else ()),
            executed_tests=(_canonical_identities(summary.executed) if summary is not None else ()),
            evidence=state.evidence,
        )

    def _map_error_status(
        self,
        error: BaseException,
    ) -> BugFixPhaseStatus | None:
        return classify_phase_error(error)

    def _capture_error_summary(
        self,
        state: _PhaseState,
        error: BaseException,
    ) -> None:
        if isinstance(error, (TestExecutionError, TestInfrastructureError)):
            state.summary = error.summary

    def _save_emergency_diagnostic(
        self,
        state: _PhaseState,
        error: BaseException,
    ) -> None:
        diagnostic = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        path = self._evidence_store.save_text(
            f"{state.name}-emergency.txt",
            diagnostic,
        )
        state.evidence_sources["emergency"] = path

    def _save_secondary_diagnostic(
        self,
        state: _PhaseState,
        kind: str,
        error: BaseException,
    ) -> None:
        try:
            path = self._evidence_store.save_text(
                f"{state.name}-{kind}-failure.txt",
                "".join(
                    traceback.format_exception(
                        type(error),
                        error,
                        error.__traceback__,
                    )
                ),
            )
            protected = self._evidence_store.protect_artifact(
                path,
                f"{state.name}-evidence",
            )
            state.evidence[f"{kind}_failure"] = self._relative_protected_path(protected)
        except Exception as diagnostic_error:  # noqa: BLE001 - retain the primary error
            state.secondary_diagnostics.append(f"{kind}: {diagnostic_error}")

    def _persist_dependency_result(
        self,
        name: str,
        result: BugFixPhaseResult,
    ) -> BugFixPhaseResult:
        self._evidence_store.save_phase(name, result)
        return result

    def _product_projects(
        self,
        submission: GeneratedBugFixOutput,
    ) -> tuple[str, ...]:
        declared = tuple(project for project in self._project_paths if not is_test_project(project))
        return tuple(order_project_paths(declared, [*declared, *submission.app_projects]))

    def _benchmark_test_projects(self) -> tuple[str, ...]:
        declared = tuple(project for project in self._project_paths if is_test_project(project))
        return tuple(order_project_paths(declared, declared))

    def _require_single_generated_test(
        self,
        submission: GeneratedBugFixOutput,
    ) -> None:
        identities = _canonical_test_entries(submission.tests)
        if len(identities) != 1:
            raise GeneratedSubmissionError(f"Expected exactly one generated test identity, found {len(identities)}.")

    def _assert_projects_have_no_packages(
        self,
        workspace: Path,
        project_paths: Iterable[str],
        label: str,
    ) -> None:
        packages = sorted(
            str(package) for project in project_paths for package in (workspace / Path(project.replace("\\", "/"))).rglob("*.app") if ".alpackages" not in {part.casefold() for part in package.parts}
        )
        if packages:
            raise PackageInventoryError(f"Unexpected {label} packages are present: {packages}")

    def _assert_no_forbidden_package_hashes(self, workspace: Path) -> None:
        contaminated = sorted(
            str(package) for package in workspace.rglob("*.app") if ".alpackages" not in {part.casefold() for part in package.parts} and sha256_file(package) in self._generated_test_package_hashes
        )
        if contaminated:
            raise PackageInventoryError(f"Generated test package contamination detected: {contaminated}")

    def _verify_no_unexpected_workspace_packages(self, state: _PhaseState) -> None:
        if state.workspace is None:
            raise PackageInventoryError("Evaluator workspace is unavailable")
        expected = {package.resolve() for package in state.packages}
        actual = {package.resolve() for package in state.workspace.rglob("*.app") if ".alpackages" not in {part.casefold() for part in package.parts}}
        unexpected = sorted(str(package) for package in actual - expected)
        missing = sorted(str(package) for package in expected - actual)
        if unexpected or missing:
            raise PackageInventoryError(f"Workspace package inventory mismatch: missing={missing}, unexpected={unexpected}")

    def _source_description(
        self,
        *,
        generated_fix_patch: str | None = None,
        trusted_gold_patch: str | None = None,
        generated_test_patch: str | None = None,
        trusted_benchmark_patch: str | None = None,
    ) -> str:
        components = [f"trusted_commit={self._trusted_source.commit}"]
        labels = (
            ("generated_fix_patch", generated_fix_patch),
            ("trusted_gold_patch", trusted_gold_patch),
            ("generated_test_patch", generated_test_patch),
            ("trusted_benchmark_patch", trusted_benchmark_patch),
        )
        components.extend(f"{label}={patch}" for label, patch in labels if patch is not None)
        return "\n".join(components) + "\n"


def _canonical_identity(identity: TestIdentity) -> str:
    return f"{identity.codeunit_id}:{identity.function_name}"


def _canonical_identities(identities: Iterable[TestIdentity]) -> tuple[str, ...]:
    return tuple(sorted(_canonical_identity(identity) for identity in identities))


def _canonical_test_entries(tests: Iterable[TestEntry]) -> tuple[str, ...]:
    return tuple(sorted(f"{test.codeunitID}:{function_name}" for test in tests for function_name in test.functionName))


def _requested_test_identities(tests: Iterable[TestEntry]) -> tuple[TestIdentity, ...]:
    return tuple(TestIdentity(test.codeunitID, function_name) for test in tests for function_name in sorted(test.functionName))


def _require_exact_test_summary(
    summary: TestRunSummary,
    tests: Iterable[TestEntry],
    expectation: TestExpectation,
) -> None:
    expected = Counter(_requested_test_identities(tests))
    requested = Counter(summary.requested)
    discovered = Counter(summary.discovered)
    executed = Counter(summary.executed)
    if requested != expected:
        raise TestExecutionError(
            expectation,
            reason="Requested test identity multiset does not match the exact selection.",
            summary=summary,
            failure_kind=TestExecutionFailureKind.SELECTION_EVIDENCE,
        )
    if discovered != expected:
        raise TestExecutionError(
            expectation,
            reason="Discovered test identity multiset does not match the exact selection.",
            summary=summary,
            failure_kind=TestExecutionFailureKind.SELECTION_EVIDENCE,
        )
    if executed != expected:
        raise TestExecutionError(
            expectation,
            reason="Executed test identity multiset does not match the exact selection.",
            summary=summary,
            failure_kind=TestExecutionFailureKind.SELECTION_EVIDENCE,
        )
    if any(result.outcome is TestOutcome.SKIP for result in summary.results):
        raise TestExecutionError(
            expectation,
            reason="Skipped tests are not allowed.",
            summary=summary,
            failure_kind=TestExecutionFailureKind.SELECTION_EVIDENCE,
        )
    summary.require(expectation)


def _app_inventory_from_package(
    project_root: Path,
    package_path: Path,
) -> AppInventoryEntry:
    manifest_path = project_root / "app.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise PackageInventoryError(f"Failed to read project manifest {manifest_path}: {error}") from error
    if not isinstance(manifest, dict):
        raise PackageInventoryError(f"Project manifest must be a JSON object: {manifest_path}")

    package_manifest = _read_package_manifest(package_path)
    return AppInventoryEntry(
        app_id=_manifest_value(manifest, "id", manifest_path),
        name=_manifest_value(manifest, "name", manifest_path),
        publisher=_manifest_value(manifest, "publisher", manifest_path),
        version=_manifest_value(manifest, "version", manifest_path),
        package_id=_optional_manifest_value(package_manifest, "package_id"),
        scope=_optional_manifest_value(package_manifest, "scope") or "Global",
        installed=True,
        synchronized=True,
        content_hash=sha256_file(package_path),
    )


def _read_package_manifest(package_path: Path) -> dict[str, str]:
    if not zipfile.is_zipfile(package_path):
        return {}
    try:
        with zipfile.ZipFile(package_path) as package:
            manifest_name = next(
                (name for name in package.namelist() if Path(name).name.casefold() == "navxmanifest.xml"),
                None,
            )
            if manifest_name is None:
                return {}
            root = ET.fromstring(package.read(manifest_name))
    except (OSError, zipfile.BadZipFile, ET.ParseError) as error:
        raise PackageInventoryError(f"Failed to read package manifest {package_path}: {error}") from error

    values: dict[str, str] = {}
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1].casefold()
        attributes = {name.casefold(): value for name, value in element.attrib.items()}
        text = (element.text or "").strip()
        if local_name in {"packageid", "package_id"} and text:
            values.setdefault("package_id", text)
        if local_name == "scope" and text:
            values.setdefault("scope", text)
        package_id = attributes.get("packageid") or attributes.get("package_id")
        if package_id:
            values.setdefault("package_id", package_id)
        if local_name in {"package", "navxpackage"} and attributes.get("id"):
            values.setdefault("package_id", attributes["id"])
        if attributes.get("scope"):
            values.setdefault("scope", attributes["scope"])
    return values


def _manifest_value(
    project_manifest: dict[str, object],
    name: str,
    manifest_path: Path,
) -> str:
    value = project_manifest.get(name)
    if not isinstance(value, str) or not value:
        raise PackageInventoryError(f"Project manifest {manifest_path} has no non-empty {name!r}")
    return value


def _optional_manifest_value(
    package_manifest: dict[str, str],
    name: str,
) -> str | None:
    value = package_manifest.get(name)
    return value or None
