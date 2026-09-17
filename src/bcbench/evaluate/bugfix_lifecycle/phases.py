from __future__ import annotations

import json
import traceback
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from bcbench.dataset import TestEntry
from bcbench.evaluate.bugfix_lifecycle.checkpoint import CheckpointManager
from bcbench.evaluate.bugfix_lifecycle.evidence import EvidenceStore, sha256_file, sha256_text
from bcbench.evaluate.bugfix_lifecycle.models import (
    AppInventoryEntry,
    CheckpointManifest,
    ProjectPublication,
    TrustedSource,
)
from bcbench.evaluate.bugfix_lifecycle.workspace import TrustedWorkspaceBuilder
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
    TestExecutionError,
    TestExecutionFailureKind,
    TestExecutionTimeoutExpired,
    TestInfrastructureError,
)
from bcbench.operations.bc_operations import build_and_publish_projects, run_test_suite
from bcbench.operations.filesystem_operations import remove_tree
from bcbench.operations.git_operations import apply_patch
from bcbench.operations.project_operations import is_test_project, order_project_paths
from bcbench.operations.test_execution import TestExpectation, TestIdentity, TestOutcome, TestRunSummary
from bcbench.results.bugfix import BugFixPhaseResult, BugFixPhaseStatus
from bcbench.types import ContainerConfig

PatchApplier = Callable[[Path, str, str], None]
WorkspaceCleaner = Callable[[Path], None]
InventoryReader = Callable[[], Sequence[AppInventoryEntry]]


class ProjectPublisher(Protocol):
    def publish(
        self,
        repo_path: Path,
        project_paths: Sequence[str],
        container: ContainerConfig,
        version: str,
    ) -> Sequence[Path]: ...


class ExactTestRunner(Protocol):
    def run(
        self,
        tests: Sequence[TestEntry],
        expectation: TestExpectation,
        container: ContainerConfig,
        repo_path: Path,
    ) -> TestRunSummary: ...


class DefaultProjectPublisher:
    def publish(
        self,
        repo_path: Path,
        project_paths: Sequence[str],
        container: ContainerConfig,
        version: str,
    ) -> tuple[Path, ...]:
        ordered_projects = tuple(project_paths)
        build_and_publish_projects(repo_path, list(ordered_projects), container, version)
        packages = tuple(
            sorted(
                (package for project in ordered_projects for package in (repo_path / project).rglob("*.app") if ".alpackages" not in {part.casefold() for part in package.parts}),
                key=lambda path: str(path).casefold(),
            )
        )
        if not packages:
            raise PackageInventoryError(f"Build and publish produced no application packages for projects: {ordered_projects}")
        return packages

    __call__ = publish


class DefaultExactTestRunner:
    def run(
        self,
        tests: Sequence[TestEntry],
        expectation: TestExpectation,
        container: ContainerConfig,
        repo_path: Path,
    ) -> TestRunSummary:
        test_entries = list(tests)
        summary = run_test_suite(test_entries, expectation, container, repo_path)
        _require_exact_test_summary(summary, test_entries, expectation)
        return summary

    __call__ = run


@dataclass
class _PhaseState:
    name: str
    source_description: str
    source_hash: str
    checkpoint_hash: str | None
    workspace: Path | None = None
    packages: list[Path] = field(default_factory=list)
    package_hashes: dict[Path, str] = field(default_factory=dict)
    protected_kinds: dict[Path, str] = field(default_factory=dict)
    summary: TestRunSummary | None = None
    evidence: dict[str, str] = field(default_factory=dict)
    expected_apps: tuple[AppInventoryEntry, ...] = ()


def make_not_run_phase(reason: str) -> BugFixPhaseResult:
    now = datetime.now(UTC)
    return BugFixPhaseResult(
        status=BugFixPhaseStatus.NOT_RUN,
        started_at=now,
        completed_at=now,
        error_message=reason,
    )


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
        publisher: ProjectPublisher | None = None,
        test_runner: ExactTestRunner | None = None,
        patch_applier: PatchApplier = apply_patch,
        workspace_cleaner: WorkspaceCleaner = remove_tree,
        inventory_reader: InventoryReader | None = None,
    ) -> None:
        self._trusted_source = trusted_source
        self._workspace_builder = workspace_builder
        self._checkpoint_manager = checkpoint_manager
        self._evidence_store = evidence_store
        self._container = container
        self._version = version
        self._project_paths = tuple(project_paths)
        self._publisher = publisher or DefaultProjectPublisher()
        self._test_runner = test_runner or DefaultExactTestRunner()
        self._patch_applier = patch_applier
        self._workspace_cleaner = workspace_cleaner
        self._inventory_reader = inventory_reader
        self._generated_test_package_hashes: set[str] = set()

    def run_test_red(
        self,
        submission: GeneratedBugFixOutput,
        s0: CheckpointManifest,
    ) -> BugFixPhaseResult:
        source_description = self._source_description(generated_test_patch=submission.test_patch)

        def action(state: _PhaseState) -> None:
            self._require_single_generated_test(submission)
            self._restore(s0)
            state.workspace = self._create_workspace(state.name)
            self._apply_generated(
                state.workspace,
                submission.test_patch,
                "test-red generated test patch",
            )
            self._publish_batch(state, self._product_projects(submission), "test-red-product")
            test_packages = self._publish_batch(
                state,
                submission.test_projects,
                "generated-test",
            )
            self._generated_test_package_hashes.update(sha256_file(package) for package in test_packages)
            self._verify_no_unexpected_workspace_packages(state)
            state.summary = self._run_exact_tests(
                submission.tests,
                TestExpectation.ALL_FAIL,
                state.workspace,
            )

        return self._execute_phase("test-red", s0, source_description, action)

    def run_test_gold(
        self,
        submission: GeneratedBugFixOutput,
        s0: CheckpointManifest,
        gold_patch: str,
    ) -> BugFixPhaseResult:
        source_description = self._source_description(
            trusted_gold_patch=gold_patch,
            generated_test_patch=submission.test_patch,
        )
        source_hash = sha256_text(source_description)

        def action(state: _PhaseState) -> None:
            self._require_single_generated_test(submission)
            self._restore(s0)
            state.workspace = self._create_workspace(state.name)
            self._apply_trusted(
                state.workspace,
                gold_patch,
                "test-gold trusted gold patch",
            )
            self._apply_generated(
                state.workspace,
                submission.test_patch,
                "test-gold generated test patch",
            )
            self._publish_batch(
                state,
                self._product_projects(submission),
                f"gold-product-{source_hash}",
            )
            test_packages = self._publish_batch(
                state,
                submission.test_projects,
                "generated-test",
            )
            self._generated_test_package_hashes.update(sha256_file(package) for package in test_packages)
            self._verify_no_unexpected_workspace_packages(state)
            state.summary = self._run_exact_tests(
                submission.tests,
                TestExpectation.ALL_PASS,
                state.workspace,
            )

        return self._execute_phase("test-gold", s0, source_description, action)

    def run_fix_build(
        self,
        submission: GeneratedBugFixOutput,
        s0: CheckpointManifest,
    ) -> tuple[BugFixPhaseResult, CheckpointManifest | None]:
        source_description = self._source_description(generated_fix_patch=submission.fix_patch)
        fixed_manifest: CheckpointManifest | None = None

        def action(state: _PhaseState) -> None:
            nonlocal fixed_manifest
            self._restore(s0)
            state.workspace = self._create_workspace(state.name)
            self._apply_generated(
                state.workspace,
                submission.fix_patch,
                "fix-build generated fix patch",
            )
            self._assert_projects_have_no_packages(
                state.workspace,
                submission.test_projects,
                "generated test",
            )
            self._publish_batch(
                state,
                self._product_projects(submission),
                "fixed-product",
            )
            self._verify_no_unexpected_workspace_packages(state)
            self._assert_no_forbidden_package_hashes(state.workspace)
            fixed_manifest = self._checkpoint_manager.capture(
                "fixed",
                state.expected_apps,
            )
            state.checkpoint_hash = fixed_manifest.sha256
            state.evidence["fixed_checkpoint"] = str(fixed_manifest.backup_path)

        result = self._execute_phase("fix-build", s0, source_description, action)
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
            self._require_single_generated_test(submission)
            state.workspace = self._create_workspace(state.name)
            self._apply_generated(
                state.workspace,
                submission.fix_patch,
                "generated-pair generated fix patch",
            )
            self._apply_generated(
                state.workspace,
                submission.test_patch,
                "generated-pair generated test patch",
            )
            test_packages = self._publish_batch(
                state,
                submission.test_projects,
                "generated-test",
            )
            self._generated_test_package_hashes.update(sha256_file(package) for package in test_packages)
            self._verify_no_unexpected_workspace_packages(state)
            state.summary = self._run_exact_tests(
                submission.tests,
                TestExpectation.ALL_PASS,
                state.workspace,
            )

        return self._execute_phase("generated-pair", sf, source_description, action)

    def run_benchmark_fix(
        self,
        submission: GeneratedBugFixOutput,
        sf: CheckpointManifest,
        benchmark_patch: str,
        fail_to_pass: Sequence[TestEntry],
        pass_to_pass: Sequence[TestEntry],
    ) -> BugFixPhaseResult:
        benchmark_tests = (*fail_to_pass, *pass_to_pass)
        source_description = self._source_description(
            generated_fix_patch=submission.fix_patch,
            trusted_benchmark_patch=benchmark_patch,
        )

        def action(state: _PhaseState) -> None:
            self._restore(sf)
            state.workspace = self._create_workspace(state.name)
            self._assert_projects_have_no_packages(
                state.workspace,
                submission.test_projects,
                "generated test",
            )
            self._apply_generated(
                state.workspace,
                submission.fix_patch,
                "benchmark-fix generated fix patch",
            )
            self._apply_trusted(
                state.workspace,
                benchmark_patch,
                "benchmark-fix trusted benchmark patch",
            )
            self._assert_projects_have_no_packages(
                state.workspace,
                submission.test_projects,
                "generated test",
            )
            self._publish_batch(
                state,
                self._benchmark_test_projects(),
                "benchmark-test",
            )
            self._verify_no_unexpected_workspace_packages(state)
            self._assert_no_forbidden_package_hashes(state.workspace)
            state.summary = self._run_exact_tests(
                benchmark_tests,
                TestExpectation.ALL_PASS,
                state.workspace,
            )

        return self._execute_phase("benchmark-fix", sf, source_description, action)

    def _execute_phase(
        self,
        name: str,
        checkpoint: CheckpointManifest,
        source_description: str,
        action: Callable[[_PhaseState], None],
    ) -> BugFixPhaseResult:
        started_at = datetime.now(UTC)
        state = _PhaseState(
            name=name,
            source_description=source_description,
            source_hash=sha256_text(source_description),
            checkpoint_hash=checkpoint.sha256,
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
            else:
                self._save_secondary_diagnostic(state, "cleanup", cleanup_error)

        result = self._phase_result(
            state,
            status=status,
            started_at=started_at,
            error_message=error_message,
        )
        self._evidence_store.save_phase(name, result)
        if unexpected_error is not None:
            raise unexpected_error.with_traceback(unexpected_error.__traceback__)
        return result

    def _restore(self, manifest: CheckpointManifest) -> None:
        self._checkpoint_manager.restore(manifest, manifest.apps)

    def _create_workspace(self, name: str) -> Path:
        try:
            return self._workspace_builder.create_evaluator_workspace(
                self._trusted_source,
                name,
            )
        except (OSError, ValueError) as error:
            raise BugFixLifecycleInfrastructureError(f"Failed to create evaluator workspace for {name}: {error}") from error

    def _apply_generated(self, workspace: Path, patch: str, patch_name: str) -> None:
        try:
            self._patch_applier(workspace, patch, patch_name)
        except PatchApplicationError as error:
            raise GeneratedSubmissionError(str(error)) from error

    def _apply_trusted(self, workspace: Path, patch: str, patch_name: str) -> None:
        try:
            self._patch_applier(workspace, patch, patch_name)
        except PatchApplicationError as error:
            raise BugFixLifecycleInfrastructureError(f"Trusted patch application failed: {error}") from error

    def _publish_batch(
        self,
        state: _PhaseState,
        project_paths: Sequence[str],
        protected_kind: str,
    ) -> tuple[Path, ...]:
        if not project_paths:
            return ()
        if state.workspace is None:
            raise BugFixLifecycleInfrastructureError("Evaluator workspace is unavailable")
        try:
            publish = getattr(self._publisher, "publish", self._publisher)
            returned_packages = tuple(
                publish(
                    state.workspace,
                    tuple(project_paths),
                    self._container,
                    self._version,
                )
            )
        except (OSError, ValueError) as error:
            raise PackageInventoryError(f"Project publication infrastructure failed: {error}") from error
        publication = ProjectPublication(
            project_paths=tuple(project_paths),
            package_paths=tuple(package if package.is_absolute() else state.workspace / package for package in returned_packages),
        )
        self._verify_publication(
            state,
            publication,
            allow_generated_test=protected_kind == "generated-test",
        )
        state.packages.extend(publication.package_paths)
        state.package_hashes.update((package.resolve(), sha256_file(package)) for package in publication.package_paths)
        state.protected_kinds.update(dict.fromkeys(publication.package_paths, protected_kind))
        self._verify_runtime_inventory(state)
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

        if not allow_generated_test:
            forbidden = self._generated_test_package_hashes
            contaminated = sorted(str(package) for package in packages if sha256_file(package) in forbidden)
            if contaminated:
                raise PackageInventoryError(f"Generated test packages are forbidden in this phase: {contaminated}")

    def _verify_runtime_inventory(self, state: _PhaseState) -> None:
        if self._inventory_reader is None:
            return
        try:
            inventory = tuple(self._inventory_reader())
        except (OSError, ValueError) as error:
            raise PackageInventoryError(f"Failed to read installed application inventory: {error}") from error

        unhealthy = [app.name for app in inventory if not app.installed or not app.synchronized]
        if unhealthy:
            raise PackageInventoryError(f"Applications are not installed and synchronized: {sorted(unhealthy)}")

        package_hashes = {sha256_file(package) for package in state.packages}
        inventory_hashes = {app.content_hash for app in inventory if app.content_hash is not None}
        missing_hashes = sorted(package_hashes - inventory_hashes)
        if missing_hashes:
            raise PackageInventoryError(f"Published package hashes are absent from installed inventory: {missing_hashes}")

        baseline_keys = {_inventory_key(app) for app in state.expected_apps}
        allowed_hashes = {app.content_hash for app in state.expected_apps if app.content_hash is not None} | package_hashes
        unexpected = [
            app.name for app in inventory if (app.content_hash is not None and app.content_hash not in allowed_hashes) or (app.content_hash is None and _inventory_key(app) not in baseline_keys)
        ]
        if unexpected:
            raise PackageInventoryError(f"Unexpected applications are installed: {sorted(unexpected)}")
        state.expected_apps = inventory

    def _run_exact_tests(
        self,
        tests: Sequence[TestEntry],
        expectation: TestExpectation,
        workspace: Path,
    ) -> TestRunSummary:
        run = getattr(self._test_runner, "run", self._test_runner)
        summary = run(
            tuple(tests),
            expectation,
            self._container,
            workspace,
        )
        _require_exact_test_summary(summary, tests, expectation)
        return summary

    def _persist_phase_artifacts(self, state: _PhaseState) -> None:
        source_path = self._evidence_store.save_submission(
            f"{state.name}-source.txt",
            state.source_description,
        )
        state.evidence["source"] = str(source_path)

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
        for index, package in enumerate(unique_packages):
            state.package_hashes[package] = sha256_file(package)
            kind = state.protected_kinds.get(package, state.name)
            protected = self._evidence_store.protect_artifact(package, kind)
            state.evidence[f"package_{index}"] = str(protected)

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
            state.evidence["tests"] = str(tests_path)

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
        return BugFixPhaseResult(
            status=status,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            error_message=error_message,
            source_hash=state.source_hash,
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
        state.evidence["emergency"] = str(path)

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
            state.evidence[f"{kind}_failure"] = str(path)
        except Exception as diagnostic_error:  # noqa: BLE001 - retain the primary error
            state.evidence[f"{kind}_diagnostic_error"] = str(diagnostic_error)

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


def _inventory_key(app: AppInventoryEntry) -> tuple[str, ...]:
    return (
        app.app_id,
        app.name,
        app.publisher,
        app.version,
        app.package_id or "",
        app.scope,
    )
