from __future__ import annotations

import json
import zipfile
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from shutil import rmtree

import pytest

from bcbench.dataset import TestEntry
from bcbench.evaluate.bugfix_lifecycle import (
    AppInventoryEntry,
    BugFixPhaseRunner,
    CheckpointManifest,
    ContainerIdentity,
    InventoryVerifier,
    ProjectPublication,
    TrustedSource,
    make_invalid_submission_phase,
    make_not_run_phase,
    sha256_file,
)
from bcbench.evaluate.bugfix_lifecycle import phases as phases_module
from bcbench.evaluate.bugfix_output import GeneratedBugFixOutput
from bcbench.exceptions import (
    BuildError,
    BuildTimeoutExpired,
    CheckpointInfrastructureError,
    GeneratedSubmissionError,
    PatchApplicationError,
    PhaseExecutionInfrastructureError,
    TestExecutionError,
    TestExecutionFailureKind,
    TestInfrastructureError,
)
from bcbench.operations.bc_operations import TestSuiteEvidence
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


def _sha256(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _summary(
    tests: Sequence[TestEntry],
    outcome: TestOutcome,
    *,
    discovered: Sequence[TestIdentity] | None = None,
    executed: Sequence[TestIdentity] | None = None,
) -> TestSuiteEvidence:
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
            (workspace / project / "source.al").write_text(project, encoding="utf-8")
            project_name = Path(project).name
            (workspace / project / "app.json").write_text(
                json.dumps(
                    {
                        "id": f"{len(project_name):08d}-2222-2222-2222-222222222222",
                        "name": project_name,
                        "publisher": "BCBench",
                        "version": "1.0.0.0",
                    }
                ),
                encoding="utf-8",
            )
        return workspace


class FakeCheckpointManager:
    def __init__(
        self,
        calls: list[tuple[object, ...]],
        fixed: CheckpointManifest,
        runtime_inventory: list[AppInventoryEntry],
    ) -> None:
        self.calls = calls
        self.fixed = fixed
        self.runtime_inventory = runtime_inventory

    def restore(self, manifest: CheckpointManifest, expected_apps: Sequence[AppInventoryEntry]) -> None:
        self.calls.append(("restore", manifest.name, tuple(app.name for app in expected_apps)))
        self.runtime_inventory[:] = expected_apps

    def capture(self, name: str, expected_apps: Sequence[AppInventoryEntry]) -> CheckpointManifest:
        self.calls.append(("capture", name, tuple(app.name for app in expected_apps)))
        return CheckpointManifest(
            name=self.fixed.name,
            backup_path=self.fixed.backup_path,
            sha256=self.fixed.sha256,
            database_name=self.fixed.database_name,
            database_folder=self.fixed.database_folder,
            container=self.fixed.container,
            apps=tuple(expected_apps),
        )


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

    def save_inventory(self, name: str, expected: object, actual: object) -> Path:
        path = self.root / "inventories" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"actual": actual, "expected": expected}),
            encoding="utf-8",
        )
        return path

    def protect_artifact(self, source: Path, kind: str) -> Path:
        self.calls.append(("protect", kind, source.name))
        destination = self.root / kind / f"{sha256_file(source)[:8]}-{source.name}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        return destination

    def relative_protected_path(self, path: Path) -> Path:
        return path.relative_to(self.root) if path.is_relative_to(self.root) else Path(path.name)


class FakePublisher:
    def __init__(
        self,
        calls: list[tuple[object, ...]],
        runtime_inventory: list[AppInventoryEntry],
    ) -> None:
        self.calls = calls
        self.runtime_inventory = runtime_inventory
        self.error: Exception | None = None

    def __call__(
        self,
        repo_path: Path,
        project_paths: Sequence[str],
        _container: ContainerConfig,
        _version: str,
        _evidence_directory: Path,
    ) -> ProjectPublication:
        self.calls.append(("publish", tuple(project_paths)))
        _evidence_directory.mkdir(parents=True, exist_ok=True)
        (_evidence_directory / "command.json").write_text("build command", encoding="utf-8")
        (_evidence_directory / "stdout.txt").write_text("build stdout", encoding="utf-8")
        (_evidence_directory / "stderr.txt").write_text("build stderr", encoding="utf-8")
        if self.error is not None:
            raise self.error
        packages = []
        apps = []
        for project in project_paths:
            package = repo_path / project / "output" / f"{Path(project).name}.app"
            package.parent.mkdir(parents=True, exist_ok=True)
            package.write_bytes(project.encode())
            packages.append(package)
            name = Path(project).name
            app = AppInventoryEntry(
                app_id=f"{len(name):08d}-2222-2222-2222-222222222222",
                name=name,
                publisher="BCBench",
                version="1.0.0.0",
                package_id=None,
                scope="Global",
                installed=True,
                synchronized=True,
                content_hash=sha256_file(package),
            )
            apps.append(app)
            self.runtime_inventory[:] = [installed for installed in self.runtime_inventory if installed.app_id != app.app_id]
            self.runtime_inventory.append(app)
        return ProjectPublication(
            project_paths=tuple(project_paths),
            package_paths=tuple(packages),
            apps=tuple(apps),
        )


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
        evidence_directory: Path,
    ) -> TestRunSummary:
        self.calls.append(("test", expectation, tuple(tests)))
        evidence_directory.mkdir(parents=True, exist_ok=True)
        (evidence_directory / "command.json").write_text("test command", encoding="utf-8")
        (evidence_directory / "stdout.txt").write_text("test stdout", encoding="utf-8")
        (evidence_directory / "stderr.txt").write_text("test stderr", encoding="utf-8")
        (evidence_directory / "discovery-50100.json").write_text("{}", encoding="utf-8")
        (evidence_directory / "results-50100.xml").write_text("<testsuite />", encoding="utf-8")
        if self.error is not None:
            raise self.error
        return TestSuiteEvidence(
            summary=self.summary or _summary(tests, self.outcome),
            command_path=evidence_directory / "command.json",
            stdout_path=evidence_directory / "stdout.txt",
            stderr_path=evidence_directory / "stderr.txt",
            discovery_paths=(evidence_directory / "discovery-50100.json",),
            junit_paths=(evidence_directory / "results-50100.xml",),
        )


class ContractPublisher:
    def __init__(
        self,
        publisher: FakePublisher,
        container: ContainerConfig,
        version: str,
    ) -> None:
        self._publisher = publisher
        self._container = container
        self._version = version

    def build_and_publish(
        self,
        repo_path: Path,
        project_paths: tuple[str, ...],
    ) -> tuple[Path, ...]:
        evidence_directory = repo_path / "evidence" / "contract-publication" / str(len(self._publisher.calls))
        return self._publisher(
            repo_path,
            project_paths,
            self._container,
            self._version,
            evidence_directory,
        ).package_paths


class ContractTestRunner:
    def __init__(
        self,
        runner: FakeTestRunner,
        container: ContainerConfig,
    ) -> None:
        self._runner = runner
        self._container = container

    def run(
        self,
        tests: tuple[TestEntry, ...],
        expectation: TestExpectation,
        repo_path: Path,
    ) -> TestRunSummary:
        evidence_directory = repo_path / "evidence" / "contract-tests"
        return self._runner(
            tests,
            expectation,
            self._container,
            repo_path,
            evidence_directory,
        ).summary


@pytest.fixture
def harness(tmp_path: Path):
    calls: list[tuple[object, ...]] = []
    source = TrustedSource(repository=tmp_path / "source.git", commit="1" * 40)
    s0 = _manifest(tmp_path, "baseline")
    sf = _manifest(tmp_path, "fixed")
    workspace_builder = FakeWorkspaceBuilder(tmp_path / "workspaces", calls)
    runtime_inventory = [_app()]
    checkpoint_manager = FakeCheckpointManager(calls, sf, runtime_inventory)
    evidence_store = FakeEvidenceStore(tmp_path / "evidence", calls)
    publisher = FakePublisher(calls, runtime_inventory)
    test_runner = FakeTestRunner(calls)
    patch_calls: list[tuple[str, str]] = []

    def apply_patch(_workspace: Path, patch: str, patch_name: str) -> None:
        patch_calls.append((patch, patch_name))
        calls.append(("patch", patch, patch_name))
        (_workspace / f"declared-{patch}.al").write_text(patch, encoding="utf-8")

    cleanup_calls: list[Path] = []
    hash_calls: list[tuple[Path, str]] = []

    def hash_workspace(workspace: Path) -> str:
        relevant_files = tuple(
            sorted(
                (path for path in workspace.rglob("*") if path.is_file() and not {"output", ".alpackages", "evidence"}.intersection(part.casefold() for part in path.relative_to(workspace).parts)),
                key=lambda path: path.relative_to(workspace).as_posix(),
            )
        )
        digest = sha256()
        for path in relevant_files:
            digest.update(path.relative_to(workspace).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        value = digest.hexdigest()
        hash_calls.append((workspace, value))
        return value

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
        workspace_hasher=hash_workspace,
        inventory_reader=lambda: tuple(runtime_inventory),
    )
    return {
        "calls": calls,
        "source": source,
        "s0": s0,
        "sf": sf,
        "workspace_builder": workspace_builder,
        "checkpoint_manager": checkpoint_manager,
        "evidence": evidence_store,
        "publisher": publisher,
        "test_runner": test_runner,
        "patch_calls": patch_calls,
        "cleanup_calls": cleanup_calls,
        "hash_calls": hash_calls,
        "runtime_inventory": runtime_inventory,
        "runner": runner,
    }


def test_phase_runner_accepts_task9_contract_only_adapters(harness) -> None:
    container = ContainerConfig(name="bc", username="user", password="pass", company="CRONUS")
    harness["test_runner"].outcome = TestOutcome.FAIL
    harness["runner"]._publisher = ContractPublisher(harness["publisher"], container, "27.0")
    harness["runner"]._test_runner = ContractTestRunner(harness["test_runner"], container)

    result = harness["runner"].run_test_red(_submission(), harness["s0"])

    assert result.status is BugFixPhaseStatus.PASSED, result.error_message
    assert result.requested_tests == ("50100:Regression",)
    assert len(result.package_hashes) == 2


def test_run_test_red_restores_builds_test_last_and_requires_one_genuine_failure(harness) -> None:
    harness["test_runner"].outcome = TestOutcome.FAIL

    result = harness["runner"].run_test_red(_submission(), harness["s0"])

    assert result.status is BugFixPhaseStatus.PASSED
    assert result.trusted_source_commit == harness["source"].commit
    assert result.trusted_source_hash == harness["hash_calls"][0][1]
    assert result.generated_fix_patch_hash is None
    assert result.generated_test_patch_hash == _sha256("T")
    assert result.gold_patch_hash is None
    assert result.benchmark_patch_hash is None
    assert result.materialized_source_hash == result.source_hash
    assert result.container_id == "container-id"
    assert result.image_id == "image-id"
    assert result.hostname == "bc"
    assert result.mounts == ()
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
    assert result.gold_patch_hash == _sha256("G")
    assert result.generated_test_patch_hash == _sha256("T")
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
    assert harness["calls"].index(product_protection) < harness["calls"].index(("publish", ("src/Tests",)))
    assert ("test", TestExpectation.ALL_PASS, _submission().tests) in harness["calls"]
    assert "gold_product_source" in result.evidence


def test_gold_verifies_product_and_test_tree_immediately_before_each_build(harness) -> None:
    events: list[tuple[str, str | tuple[str, ...]]] = []
    original_hasher = harness["runner"]._workspace_hasher
    original_publisher = harness["runner"]._publisher

    def hash_workspace(workspace: Path) -> str:
        value = original_hasher(workspace)
        events.append(("hash", value))
        return value

    def publish(*args, **kwargs):
        events.append(("publish", tuple(args[1])))
        return original_publisher(*args, **kwargs)

    harness["runner"]._workspace_hasher = hash_workspace
    harness["runner"]._publisher = publish

    result = harness["runner"].run_test_gold(_submission(), harness["s0"], "G")

    assert result.status is BugFixPhaseStatus.PASSED
    product_hash = next(value for kind, value in events if kind == "hash" and value != events[0][1])
    test_hash = result.materialized_source_hash
    assert events == [
        ("hash", events[0][1]),
        ("hash", product_hash),
        ("hash", product_hash),
        ("publish", ("src/App",)),
        ("hash", test_hash),
        ("hash", test_hash),
        ("publish", ("src/Tests",)),
    ]


def test_workspace_mutation_after_apply_blocks_publisher_as_infrastructure_error(harness) -> None:
    hashes = iter(("baseline", "expected", "mutated"))
    harness["runner"]._workspace_hasher = lambda _workspace: next(hashes)

    result = harness["runner"].run_fix_build(_submission(), harness["s0"])[0]

    assert result.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert "tree hash" in result.error_message.lower()
    assert not [call for call in harness["calls"] if call[0] == "publish"]


def test_generated_patch_hash_is_rechecked_before_apply(harness) -> None:
    submission = _submission()
    object.__setattr__(submission, "fix_patch", "tampered")

    result = harness["runner"].run_fix_build(submission, harness["s0"])[0]

    assert result.status is BugFixPhaseStatus.INVALID_SUBMISSION
    assert not harness["patch_calls"]
    assert not [call for call in harness["calls"] if call[0] == "publish"]


@pytest.mark.parametrize(
    ("phase_name", "expected_hashes"),
    [
        ("test-red", (None, _sha256("T"), None, None)),
        ("test-gold", (None, _sha256("T"), _sha256("G"), None)),
        ("fix-build", (_sha256("F"), None, None, None)),
        ("generated-pair", (_sha256("F"), _sha256("T"), None, None)),
        ("benchmark-fix", (_sha256("F"), None, None, _sha256("H"))),
    ],
)
def test_each_phase_persists_only_its_patch_hashes_and_checkpoint_container(
    harness,
    phase_name: str,
    expected_hashes: tuple[str | None, str | None, str | None, str | None],
) -> None:
    submission = _submission()
    checkpoint = harness["s0"]
    if phase_name == "test-red":
        harness["test_runner"].outcome = TestOutcome.FAIL
        result = harness["runner"].run_test_red(submission, checkpoint)
    elif phase_name == "test-gold":
        result = harness["runner"].run_test_gold(submission, checkpoint, "G")
    elif phase_name == "fix-build":
        result = harness["runner"].run_fix_build(submission, checkpoint)[0]
    elif phase_name == "generated-pair":
        fixed_identity = ContainerIdentity(
            container_id="fixed-container-id",
            image_id="fixed-image-id",
            hostname="fixed-host",
            mounts=(r"C:\fixed:C:\database",),
        )
        checkpoint = CheckpointManifest(
            name=harness["sf"].name,
            backup_path=harness["sf"].backup_path,
            sha256=harness["sf"].sha256,
            database_name=harness["sf"].database_name,
            database_folder=harness["sf"].database_folder,
            container=fixed_identity,
            apps=harness["sf"].apps,
        )
        red = make_not_run_phase("red").model_copy(update={"executed_tests": ("50100:Regression",)})
        result = harness["runner"].run_generated_pair(submission, checkpoint, red)
    else:
        result = harness["runner"].run_benchmark_fix(
            submission,
            checkpoint,
            "H",
            (TestEntry(codeunitID=10, functionName=frozenset({"FailsBefore"})),),
        )

    assert result.status is BugFixPhaseStatus.PASSED
    assert (
        result.generated_fix_patch_hash,
        result.generated_test_patch_hash,
        result.gold_patch_hash,
        result.benchmark_patch_hash,
    ) == expected_hashes
    assert result.container_id == checkpoint.container.container_id
    assert result.image_id == checkpoint.container.image_id
    assert result.hostname == checkpoint.container.hostname
    assert result.mounts == checkpoint.container.mounts
    assert result.trusted_source_commit == harness["source"].commit
    assert result.trusted_source_hash is not None
    assert result.materialized_source_hash == result.source_hash
    provenance_path = harness["evidence"].root / result.evidence["provenance"]
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["materialized_source_hash"] == result.materialized_source_hash
    assert provenance["container_id"] == result.container_id
    assert provenance["generated_fix_patch_hash"] == result.generated_fix_patch_hash
    assert provenance["generated_test_patch_hash"] == result.generated_test_patch_hash
    assert provenance["gold_patch_hash"] == result.gold_patch_hash
    assert provenance["benchmark_patch_hash"] == result.benchmark_patch_hash


def test_missing_junit_through_phase_runner_is_infrastructure_error_with_evidence(harness) -> None:
    harness["test_runner"].outcome = TestOutcome.FAIL
    harness["test_runner"].error = FileNotFoundError("Missing JUnit results for codeunit 50100")

    result = harness["runner"].run_test_red(_submission(), harness["s0"])

    assert result.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert "Missing JUnit results" in result.error_message
    assert "provenance" in result.evidence
    assert any(call[0] == "save-phase" and call[1] == "test-red" for call in harness["calls"])


def test_missing_source_after_expected_hash_capture_blocks_build(harness) -> None:
    original_hasher = harness["runner"]._workspace_hasher
    call_count = 0

    def delete_source_before_verification(workspace: Path) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            (workspace / "src" / "App" / "source.al").unlink()
        return original_hasher(workspace)

    harness["runner"]._workspace_hasher = delete_source_before_verification

    result = harness["runner"].run_fix_build(_submission(), harness["s0"])[0]

    assert result.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert "tree hash mismatch" in result.error_message
    assert not [call for call in harness["calls"] if call[0] == "publish"]


def test_phase_runner_requires_inventory_reader(harness) -> None:
    with pytest.raises(ValueError, match="inventory"):
        BugFixPhaseRunner(
            trusted_source=harness["source"],
            workspace_builder=harness["workspace_builder"],
            checkpoint_manager=harness["checkpoint_manager"],
            evidence_store=harness["evidence"],
            container=ContainerConfig(name="bc", username="user", password="pass", company="CRONUS"),
            version="27.0",
            inventory_reader=None,
        )


def test_phase_runner_requires_evidence_store(harness) -> None:
    with pytest.raises(ValueError, match="evidence"):
        BugFixPhaseRunner(
            trusted_source=harness["source"],
            workspace_builder=harness["workspace_builder"],
            checkpoint_manager=harness["checkpoint_manager"],
            evidence_store=None,
            container=ContainerConfig(name="bc", username="user", password="pass", company="CRONUS"),
            version="27.0",
            inventory_reader=lambda: (_app(),),
        )


def test_invalid_generated_test_does_not_block_independent_fix_and_pair_does_not_restore_sf(harness) -> None:
    submission = _submission()
    harness["test_runner"].outcome = TestOutcome.PASS

    phase, fixed = harness["runner"].run_fix_build(submission, harness["s0"])
    red = make_invalid_submission_phase("bad generated test").model_copy(update={"executed_tests": ("50100:Regression",)})
    pair = harness["runner"].run_generated_pair(submission, fixed, red)

    assert phase.status is BugFixPhaseStatus.PASSED
    assert fixed is not None
    assert tuple(sorted(app.name for app in fixed.apps)) == ("App", "Base")
    assert pair.status is BugFixPhaseStatus.PASSED
    restores = [call for call in harness["calls"] if call[0] == "restore"]
    assert restores == [("restore", "baseline", ("Base",))]
    capture_index = harness["calls"].index(("capture", "fixed", ("App", "Base")))
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
        (*fail_to_pass, *pass_to_pass),
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


def test_benchmark_restores_sf_independently_after_invalid_generated_test(harness) -> None:
    invalid_red = make_invalid_submission_phase("invalid generated test")

    result = harness["runner"].run_benchmark_fix(
        _submission(),
        harness["sf"],
        "H",
        (TestEntry(codeunitID=10, functionName=frozenset({"FailsBefore"})),),
    )

    assert invalid_red.status is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.status is BugFixPhaseStatus.PASSED
    assert ("restore", "fixed", ("Base",)) in harness["calls"]


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


def test_restore_failure_is_infrastructure_error(harness) -> None:
    def fail_restore(*_args) -> None:
        raise CheckpointInfrastructureError("fake restore failed")

    harness["checkpoint_manager"].restore = fail_restore

    result = harness["runner"].run_fix_build(_submission(), harness["s0"])[0]

    assert result.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert "fake restore failed" in result.error_message


def test_unexpected_error_persists_emergency_diagnostic_and_propagates(harness) -> None:
    harness["publisher"].error = RuntimeError("unexpected")

    with pytest.raises(PhaseExecutionInfrastructureError, match="fix-build") as exc_info:
        harness["runner"].run_fix_build(_submission(), harness["s0"])

    assert isinstance(exc_info.value.original, RuntimeError)
    assert exc_info.value.phase_name == "fix-build"
    assert exc_info.value.result is harness["evidence"].saved_phases[-1]
    assert exc_info.value.result.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert any(call[0] == "save-text" and "unexpected" in call[2] for call in harness["calls"])
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
    assert "cleanup_failure" in result.evidence
    assert harness["evidence"].saved_phases[-1] == result


def test_package_hashes_survive_real_workspace_cleanup(harness) -> None:
    harness["test_runner"].outcome = TestOutcome.FAIL
    harness["runner"]._workspace_cleaner = rmtree

    result = harness["runner"].run_test_red(_submission(), harness["s0"])

    assert result.status is BugFixPhaseStatus.PASSED
    assert len(result.package_hashes) == 2
    assert not harness["cleanup_calls"]


def test_fix_capture_uses_verified_installed_and_synchronized_inventory(harness) -> None:
    result, manifest = harness["runner"].run_fix_build(_submission(), harness["s0"])

    assert result.status is BugFixPhaseStatus.PASSED
    assert manifest is not None
    assert tuple(sorted(app.name for app in manifest.apps)) == ("App", "Base")
    assert ("capture", "fixed", ("App", "Base")) in harness["calls"]


def test_unhealthy_runtime_inventory_is_infrastructure_error(harness) -> None:
    unhealthy = _app().to_dict()
    unhealthy["installed"] = False
    harness["runner"]._inventory_verifier = InventoryVerifier(
        lambda: (AppInventoryEntry.from_dict(unhealthy),),
        harness["evidence"],
    )

    result = harness["runner"].run_fix_build(_submission(), harness["s0"])[0]

    assert result.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert "installed and synchronized" in result.error_message


@pytest.mark.parametrize("inventory_kind", ["missing", "duplicate", "unexpected"])
def test_exact_checkpoint_inventory_rejects_missing_duplicate_and_unexpected(
    harness,
    inventory_kind: str,
) -> None:
    baseline = _app()
    unexpected = AppInventoryEntry(
        **{
            **baseline.to_dict(),
            "app_id": "99999999-9999-9999-9999-999999999999",
            "name": "Unexpected",
            "content_hash": "b" * 64,
        }
    )
    inventories = {
        "missing": (),
        "duplicate": (baseline, baseline),
        "unexpected": (baseline, unexpected),
    }
    harness["runner"]._inventory_verifier = InventoryVerifier(
        lambda: inventories[inventory_kind],
        harness["evidence"],
    )

    result = harness["runner"].run_fix_build(_submission(), harness["s0"])[0]

    assert result.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert "inventory" in result.error_message.lower()
    assert any(key.startswith("inventory_") for key in result.evidence)


def test_inventory_rejects_same_hash_with_different_identity(harness) -> None:
    baseline = _app()
    forged = AppInventoryEntry(
        **{
            **baseline.to_dict(),
            "app_id": "99999999-9999-9999-9999-999999999999",
            "name": "Forged",
        }
    )
    harness["runner"]._inventory_verifier = InventoryVerifier(
        lambda: (forged,),
        harness["evidence"],
    )

    result = harness["runner"].run_fix_build(_submission(), harness["s0"])[0]

    assert result.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert "same" in result.error_message.lower() or "different identity" in result.error_message.lower()


def test_fix_build_rejects_installed_generated_test_contamination(harness) -> None:
    original_publish = harness["publisher"].__call__

    def publish_with_contamination(*args, **kwargs):
        publication = original_publish(*args, **kwargs)
        if publication.project_paths == ("src/App",):
            harness["runtime_inventory"].append(
                AppInventoryEntry(
                    app_id="77777777-7777-7777-7777-777777777777",
                    name="Tests",
                    publisher="BCBench",
                    version="1.0.0.0",
                    package_id=None,
                    scope="Global",
                    installed=True,
                    synchronized=True,
                    content_hash="7" * 64,
                )
            )
        return publication

    harness["runner"]._publisher = publish_with_contamination

    result = harness["runner"].run_fix_build(_submission(), harness["s0"])[0]

    assert result.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert "unexpected" in result.error_message.lower()


def test_trusted_product_build_failure_is_infrastructure_but_generated_fix_is_failed(harness) -> None:
    harness["publisher"].error = BuildError("src/App", "compiler")

    trusted = harness["runner"].run_test_red(_submission(), harness["s0"])
    generated = harness["runner"].run_fix_build(_submission(), harness["s0"])[0]

    assert trusted.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert generated.status is BugFixPhaseStatus.FAILED


def test_generated_test_publication_build_failure_is_failed(harness) -> None:
    original_publish = harness["publisher"].__call__

    def fail_generated_test(*args, **kwargs):
        project_paths = args[1]
        if tuple(project_paths) == ("src/Tests",):
            raise BuildError("src/Tests", "generated test compiler error")
        return original_publish(*args, **kwargs)

    harness["runner"]._publisher = fail_generated_test

    result = harness["runner"].run_test_red(_submission(), harness["s0"])

    assert result.status is BugFixPhaseStatus.FAILED
    assert "src/Tests" in result.error_message


def test_raw_phase_evidence_and_inventory_survive_workspace_cleanup(harness) -> None:
    harness["test_runner"].outcome = TestOutcome.FAIL
    harness["runner"]._workspace_cleaner = rmtree

    result = harness["runner"].run_test_red(_submission(), harness["s0"])

    protected_contents = [path.read_text(encoding="utf-8") for path in harness["evidence"].root.rglob("*") if path.is_file()]
    assert result.status is BugFixPhaseStatus.PASSED
    assert any(key.startswith("inventory_") for key in result.evidence)
    assert all(not Path(path).is_absolute() for path in result.evidence.values())
    assert "build stdout" in protected_contents
    assert "build stderr" in protected_contents
    assert "test stdout" in protected_contents
    assert "test stderr" in protected_contents
    assert "{}" in protected_contents
    assert "<testsuite />" in protected_contents


def test_raw_failure_evidence_survives_workspace_cleanup(harness) -> None:
    harness["publisher"].error = BuildError("src/App", "compiler error")
    harness["runner"]._workspace_cleaner = rmtree

    result = harness["runner"].run_fix_build(_submission(), harness["s0"])[0]

    protected_contents = [path.read_text(encoding="utf-8") for path in harness["evidence"].root.rglob("*") if path.is_file()]
    assert result.status is BugFixPhaseStatus.FAILED
    assert "build command" in protected_contents
    assert "build stdout" in protected_contents
    assert "build stderr" in protected_contents


def test_package_inventory_uses_project_identity_and_package_id(tmp_path: Path) -> None:
    project = tmp_path / "App"
    project.mkdir()
    (project / "app.json").write_text(
        json.dumps(
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "name": "Product",
                "publisher": "BCBench",
                "version": "27.0.0.0",
            }
        ),
        encoding="utf-8",
    )
    package = project / "Product.app"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "NavxManifest.xml",
            ('<Package Scope="Global"><PackageId>22222222-2222-2222-2222-222222222222</PackageId></Package>'),
        )

    app = phases_module._app_inventory_from_package(project, package)

    assert app.app_id == "11111111-1111-1111-1111-111111111111"
    assert app.name == "Product"
    assert app.publisher == "BCBench"
    assert app.version == "27.0.0.0"
    assert app.package_id == "22222222-2222-2222-2222-222222222222"
    assert app.scope == "Global"
    assert app.content_hash == sha256_file(package)


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
