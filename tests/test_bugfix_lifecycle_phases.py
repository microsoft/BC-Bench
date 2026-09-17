from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from shutil import rmtree

import pytest

from bcbench.dataset import TestEntry
from bcbench.evaluate.bugfix_lifecycle import (
    AppInventoryEntry,
    BugFixPhaseRunner,
    CheckpointManifest,
    ContainerIdentity,
    TrustedSource,
    make_invalid_submission_phase,
    make_not_run_phase,
    sha256_file,
)
from bcbench.evaluate.bugfix_output import GeneratedBugFixOutput
from bcbench.exceptions import (
    BuildError,
    BuildTimeoutExpired,
    CheckpointInfrastructureError,
    GeneratedSubmissionError,
    PatchApplicationError,
    TestExecutionError,
    TestExecutionFailureKind,
    TestInfrastructureError,
)
from bcbench.operations.test_execution import TestCaseResult, TestExpectation, TestIdentity, TestOutcome, TestRunSummary
from bcbench.results.bugfix import BugFixPhaseStatus
from bcbench.types import ContainerConfig


def _app(name: str = "Base") -> AppInventoryEntry:
    return AppInventoryEntry(
        app_id=f"{len(name):08d}-1111-1111-1111-111111111111",
        name=name,
        publisher="Microsoft",
        version="1.0.0.0",
        package_id=None,
        scope="Global",
        installed=True,
        synchronized=True,
        content_hash="a" * 64,
    )


def _manifest(tmp_path: Path, name: str) -> CheckpointManifest:
    backup = tmp_path / f"{name}.bak"
    backup.write_bytes(name.encode())
    return CheckpointManifest(
        name=name,
        backup_path=backup,
        sha256=(name[0] * 64),
        database_name="BC",
        database_folder=r"C:\database",
        container=ContainerIdentity(
            container_id="container-id",
            image_id="image-id",
            hostname="bc",
            mounts=(),
        ),
        apps=(_app(),),
    )


def _submission(*, tests: tuple[TestEntry, ...] | None = None) -> GeneratedBugFixOutput:
    return GeneratedBugFixOutput(
        full_patch="F+T",
        fix_patch="F",
        test_patch="T",
        app_projects=("src/App",),
        test_projects=("src/Tests",),
        tests=tests or (TestEntry(codeunitID=50100, functionName=frozenset({"Regression"})),),
    )


def _summary(
    tests: Sequence[TestEntry],
    outcome: TestOutcome,
    *,
    discovered: Sequence[TestIdentity] | None = None,
    executed: Sequence[TestIdentity] | None = None,
) -> TestRunSummary:
    requested = tuple(TestIdentity(test.codeunitID, function_name) for test in tests for function_name in sorted(test.functionName))
    discovered_identities = tuple(discovered) if discovered is not None else requested
    executed_identities = tuple(executed) if executed is not None else requested
    return TestRunSummary(
        requested=requested,
        discovered=discovered_identities,
        results=tuple(TestCaseResult(identity, outcome) for identity in executed_identities),
    )


class FakeWorkspaceBuilder:
    def __init__(self, root: Path, calls: list[tuple[object, ...]]) -> None:
        self.root = root
        self.calls = calls
        self.index = 0

    def create_evaluator_workspace(self, trusted_source: TrustedSource, name: str) -> Path:
        self.calls.append(("workspace", name, trusted_source.commit))
        self.index += 1
        workspace = self.root / f"{name}-{self.index}"
        for project in ("src/App", "src/Tests", "src/Benchmark/tests"):
            (workspace / project).mkdir(parents=True, exist_ok=True)
        return workspace


class FakeCheckpointManager:
    def __init__(self, calls: list[tuple[object, ...]], fixed: CheckpointManifest) -> None:
        self.calls = calls
        self.fixed = fixed

    def restore(self, manifest: CheckpointManifest, expected_apps: Sequence[AppInventoryEntry]) -> None:
        self.calls.append(("restore", manifest.name, tuple(app.name for app in expected_apps)))

    def capture(self, name: str, expected_apps: Sequence[AppInventoryEntry]) -> CheckpointManifest:
        self.calls.append(("capture", name, tuple(app.name for app in expected_apps)))
        return self.fixed


class FakeEvidenceStore:
    def __init__(self, root: Path, calls: list[tuple[object, ...]]) -> None:
        self.root = root
        self.calls = calls
        self.saved_phases = []

    def save_phase(self, name, result):
        self.calls.append(("save-phase", name, result.status))
        self.saved_phases.append(result)
        path = self.root / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(), encoding="utf-8")
        return path

    def save_submission(self, name: str, content: str) -> Path:
        self.calls.append(("save-submission", name, content))
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def save_text(self, name: str, diagnostic: str) -> Path:
        self.calls.append(("save-text", name, diagnostic))
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(diagnostic, encoding="utf-8")
        return path

    def protect_artifact(self, source: Path, kind: str) -> Path:
        self.calls.append(("protect", kind, source.name))
        destination = self.root / kind / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        return destination


class FakePublisher:
    def __init__(self, calls: list[tuple[object, ...]]) -> None:
        self.calls = calls
        self.error: Exception | None = None

    def __call__(self, repo_path: Path, project_paths: Sequence[str], _container: ContainerConfig, _version: str) -> tuple[Path, ...]:
        self.calls.append(("publish", tuple(project_paths)))
        if self.error is not None:
            raise self.error
        packages = []
        for project in project_paths:
            package = repo_path / project / f"{Path(project).name}.app"
            package.write_bytes(project.encode())
            packages.append(package)
        return tuple(packages)


class FakeTestRunner:
    def __init__(self, calls: list[tuple[object, ...]]) -> None:
        self.calls = calls
        self.error: Exception | None = None
        self.outcome = TestOutcome.PASS
        self.summary: TestRunSummary | None = None

    def __call__(
        self,
        tests: Sequence[TestEntry],
        expectation: TestExpectation,
        _container: ContainerConfig,
        _repo_path: Path,
    ) -> TestRunSummary:
        self.calls.append(("test", expectation, tuple(tests)))
        if self.error is not None:
            raise self.error
        return self.summary or _summary(tests, self.outcome)


@pytest.fixture
def harness(tmp_path: Path):
    calls: list[tuple[object, ...]] = []
    source = TrustedSource(repository=tmp_path / "source.git", commit="1" * 40)
    s0 = _manifest(tmp_path, "baseline")
    sf = _manifest(tmp_path, "fixed")
    workspace_builder = FakeWorkspaceBuilder(tmp_path / "workspaces", calls)
    checkpoint_manager = FakeCheckpointManager(calls, sf)
    evidence_store = FakeEvidenceStore(tmp_path / "evidence", calls)
    publisher = FakePublisher(calls)
    test_runner = FakeTestRunner(calls)
    patch_calls: list[tuple[str, str]] = []

    def apply_patch(_workspace: Path, patch: str, patch_name: str) -> None:
        patch_calls.append((patch, patch_name))
        calls.append(("patch", patch, patch_name))

    cleanup_calls: list[Path] = []

    def cleanup(workspace: Path) -> None:
        cleanup_calls.append(workspace)
        calls.append(("cleanup", workspace.name))

    runner = BugFixPhaseRunner(
        trusted_source=source,
        workspace_builder=workspace_builder,
        checkpoint_manager=checkpoint_manager,
        evidence_store=evidence_store,
        container=ContainerConfig(name="bc", username="user", password="password", company="CRONUS"),
        version="27.0",
        project_paths=("src/App", "src/Benchmark/tests"),
        publisher=publisher,
        test_runner=test_runner,
        patch_applier=apply_patch,
        workspace_cleaner=cleanup,
    )
    return {
        "calls": calls,
        "source": source,
        "s0": s0,
        "sf": sf,
        "workspace_builder": workspace_builder,
        "evidence": evidence_store,
        "publisher": publisher,
        "test_runner": test_runner,
        "patch_calls": patch_calls,
        "cleanup_calls": cleanup_calls,
        "runner": runner,
    }


def test_run_test_red_restores_builds_test_last_and_requires_one_genuine_failure(harness) -> None:
    harness["test_runner"].outcome = TestOutcome.FAIL

    result = harness["runner"].run_test_red(_submission(), harness["s0"])

    assert result.status is BugFixPhaseStatus.PASSED
    assert result.checkpoint_hash == harness["s0"].sha256
    assert result.requested_tests == ("50100:Regression",)
    assert result.discovered_tests == ("50100:Regression",)
    assert result.executed_tests == ("50100:Regression",)
    assert len(result.package_hashes) == 2
    assert harness["calls"][:7] == [
        ("restore", "baseline", ("Base",)),
        ("workspace", "test-red", harness["source"].commit),
        ("patch", "T", "test-red generated test patch"),
        ("publish", ("src/App",)),
        ("publish", ("src/Tests",)),
        ("test", TestExpectation.ALL_FAIL, _submission().tests),
        ("save-submission", "test-red-source.txt", "trusted_commit=" + harness["source"].commit + "\ngenerated_test_patch=T\n"),
    ]
    assert harness["calls"][-2][0] == "cleanup"
    assert harness["calls"][-1] == ("save-phase", "test-red", BugFixPhaseStatus.PASSED)


def test_run_test_gold_restores_s0_applies_gold_before_test_and_content_addresses_product(harness) -> None:
    harness["test_runner"].outcome = TestOutcome.PASS

    result = harness["runner"].run_test_gold(_submission(), harness["s0"], "G")

    assert result.status is BugFixPhaseStatus.PASSED
    assert harness["patch_calls"] == [
        ("G", "test-gold trusted gold patch"),
        ("T", "test-gold generated test patch"),
    ]
    assert [call for call in harness["calls"] if call[0] == "publish"] == [
        ("publish", ("src/App",)),
        ("publish", ("src/Tests",)),
    ]
    product_protection = next(call for call in harness["calls"] if call[0] == "protect" and call[2] == "App.app")
    assert product_protection[1].startswith("gold-product-")
    assert ("test", TestExpectation.ALL_PASS, _submission().tests) in harness["calls"]


def test_invalid_generated_test_does_not_block_independent_fix_and_pair_does_not_restore_sf(harness) -> None:
    submission = _submission()
    harness["test_runner"].outcome = TestOutcome.PASS

    phase, fixed = harness["runner"].run_fix_build(submission, harness["s0"])
    red = make_invalid_submission_phase("bad generated test").model_copy(update={"executed_tests": ("50100:Regression",)})
    pair = harness["runner"].run_generated_pair(submission, fixed, red)

    assert phase.status is BugFixPhaseStatus.PASSED
    assert fixed == harness["sf"]
    assert pair.status is BugFixPhaseStatus.PASSED
    restores = [call for call in harness["calls"] if call[0] == "restore"]
    assert restores == [("restore", "baseline", ("Base",))]
    capture_index = harness["calls"].index(("capture", "fixed", ("Base",)))
    pair_workspace_index = next(index for index, call in enumerate(harness["calls"]) if call[:2] == ("workspace", "generated-pair"))
    assert capture_index < pair_workspace_index
    assert harness["patch_calls"] == [
        ("F", "fix-build generated fix patch"),
        ("F", "generated-pair generated fix patch"),
        ("T", "generated-pair generated test patch"),
    ]


def test_generated_pair_runs_after_wrong_red_outcome_but_not_without_execution(harness) -> None:
    submission = _submission()
    wrong_red = make_not_run_phase("wrong red").model_copy(
        update={
            "status": BugFixPhaseStatus.FAILED,
            "requested_tests": ("50100:Regression",),
            "discovered_tests": ("50100:Regression",),
            "executed_tests": ("50100:Regression",),
        }
    )

    result = harness["runner"].run_generated_pair(submission, harness["sf"], wrong_red)
    not_run = harness["runner"].run_generated_pair(submission, harness["sf"], make_not_run_phase("red did not execute"))

    assert result.status is BugFixPhaseStatus.PASSED
    assert not_run.status is BugFixPhaseStatus.NOT_RUN


def test_benchmark_restores_sf_uses_only_fix_and_hidden_patch_and_combines_exact_tests(harness) -> None:
    fail_to_pass = [TestEntry(codeunitID=10, functionName=frozenset({"FailsBefore"}))]
    pass_to_pass = [TestEntry(codeunitID=20, functionName=frozenset({"StillPasses"}))]

    result = harness["runner"].run_benchmark_fix(
        _submission(),
        harness["sf"],
        "H",
        fail_to_pass,
        pass_to_pass,
    )

    assert result.status is BugFixPhaseStatus.PASSED
    assert ("restore", "fixed", ("Base",)) in harness["calls"]
    assert harness["patch_calls"] == [
        ("F", "benchmark-fix generated fix patch"),
        ("H", "benchmark-fix trusted benchmark patch"),
    ]
    assert ("T", "benchmark-fix generated test patch") not in harness["patch_calls"]
    assert [call for call in harness["calls"] if call[0] == "publish"] == [
        ("publish", ("src/Benchmark/tests",)),
    ]
    assert (
        "test",
        TestExpectation.ALL_PASS,
        (*fail_to_pass, *pass_to_pass),
    ) in harness["calls"]
    assert result.requested_tests == ("10:FailsBefore", "20:StillPasses")


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (GeneratedSubmissionError("invalid"), BugFixPhaseStatus.INVALID_SUBMISSION),
        (BuildError("src/App"), BugFixPhaseStatus.FAILED),
        (
            TestExecutionError(TestExpectation.ALL_PASS),
            BugFixPhaseStatus.FAILED,
        ),
        (
            TestExecutionError(
                TestExpectation.ALL_PASS,
                failure_kind=TestExecutionFailureKind.SELECTION_EVIDENCE,
            ),
            BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
        ),
        (BuildTimeoutExpired("src/App", 10), BugFixPhaseStatus.INFRASTRUCTURE_ERROR),
        (CheckpointInfrastructureError("restore"), BugFixPhaseStatus.INFRASTRUCTURE_ERROR),
        (
            TestInfrastructureError(TestExpectation.ALL_PASS, "runner"),
            BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
        ),
    ],
)
def test_generated_phase_status_mapping(harness, error: Exception, expected_status: BugFixPhaseStatus) -> None:
    harness["publisher"].error = error

    result = harness["runner"].run_fix_build(_submission(), harness["s0"])[0]

    assert result.status is expected_status
    assert result.started_at is not None
    assert result.completed_at is not None
    assert harness["evidence"].saved_phases[-1] == result


def test_generated_patch_application_failure_is_invalid_submission(harness) -> None:
    def apply_patch(_workspace: Path, _patch: str, patch_name: str) -> None:
        raise PatchApplicationError(patch_name)

    harness["runner"]._patch_applier = apply_patch

    result = harness["runner"].run_fix_build(_submission(), harness["s0"])[0]

    assert result.status is BugFixPhaseStatus.INVALID_SUBMISSION


def test_trusted_patch_failure_is_infrastructure_error(harness) -> None:
    def apply_patch(_workspace: Path, patch: str, patch_name: str) -> None:
        if patch == "G":
            raise PatchApplicationError(patch_name)

    harness["runner"]._patch_applier = apply_patch

    result = harness["runner"].run_test_gold(_submission(), harness["s0"], "G")

    assert result.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR


def test_unexpected_error_persists_emergency_diagnostic_and_propagates(harness) -> None:
    harness["publisher"].error = RuntimeError("unexpected")

    with pytest.raises(RuntimeError, match="unexpected"):
        harness["runner"].run_fix_build(_submission(), harness["s0"])

    assert any(call[0] == "save-text" and "unexpected" in call[2] for call in harness["calls"])
    assert harness["evidence"].saved_phases[-1].status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert harness["cleanup_calls"]


def test_cleanup_failure_overrides_success_and_keeps_protected_evidence(harness) -> None:
    harness["test_runner"].outcome = TestOutcome.FAIL

    def fail_cleanup(_workspace: Path) -> None:
        raise OSError("locked")

    harness["runner"]._workspace_cleaner = fail_cleanup

    result = harness["runner"].run_test_red(_submission(), harness["s0"])

    assert result.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert "cleanup" in result.error_message.lower()
    assert any(call[0] == "protect" for call in harness["calls"])
    assert harness["evidence"].saved_phases[-1] == result


def test_package_hashes_survive_real_workspace_cleanup(harness) -> None:
    harness["test_runner"].outcome = TestOutcome.FAIL
    harness["runner"]._workspace_cleaner = rmtree

    result = harness["runner"].run_test_red(_submission(), harness["s0"])

    assert result.status is BugFixPhaseStatus.PASSED
    assert len(result.package_hashes) == 2
    assert not harness["cleanup_calls"]


def test_fix_capture_uses_verified_installed_and_synchronized_inventory(harness) -> None:
    def read_inventory() -> tuple[AppInventoryEntry, ...]:
        packages = sorted((harness["workspace_builder"].root).rglob("*.app"))
        return (
            _app(),
            *(
                AppInventoryEntry(
                    app_id=f"{index:08d}-2222-2222-2222-222222222222",
                    name=package.stem,
                    publisher="BCBench",
                    version="1.0.0.0",
                    package_id=None,
                    scope="Global",
                    installed=True,
                    synchronized=True,
                    content_hash=sha256_file(package),
                )
                for index, package in enumerate(packages, start=1)
            ),
        )

    harness["runner"]._inventory_reader = read_inventory

    result, manifest = harness["runner"].run_fix_build(_submission(), harness["s0"])

    assert result.status is BugFixPhaseStatus.PASSED
    assert manifest == harness["sf"]
    assert ("capture", "fixed", ("Base", "App")) in harness["calls"]


def test_unhealthy_runtime_inventory_is_infrastructure_error(harness) -> None:
    unhealthy = _app().to_dict()
    unhealthy["installed"] = False
    harness["runner"]._inventory_reader = lambda: (AppInventoryEntry.from_dict(unhealthy),)

    result = harness["runner"].run_fix_build(_submission(), harness["s0"])[0]

    assert result.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert "installed and synchronized" in result.error_message


def test_exact_identity_multiset_rejects_duplicate_missing_and_unexpected_execution(harness) -> None:
    requested = TestIdentity(50100, "Regression")
    harness["test_runner"].summary = TestRunSummary(
        requested=(requested,),
        discovered=(requested, requested),
        results=(TestCaseResult(requested, TestOutcome.FAIL),),
    )

    result = harness["runner"].run_test_red(_submission(), harness["s0"])

    assert result.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert result.requested_tests == ("50100:Regression",)
    assert result.discovered_tests == ("50100:Regression", "50100:Regression")
