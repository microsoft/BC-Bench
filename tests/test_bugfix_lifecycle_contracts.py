from inspect import signature
from pathlib import Path
from typing import get_type_hints

from bcbench.dataset import TestEntry
from bcbench.evaluate.bugfix_lifecycle import (
    BugFixPhaseRunner,
    DefaultExactTestRunner,
    DefaultProjectPublisher,
    ExactTestRunner,
    ProjectPublisher,
)
from bcbench.evaluate.bugfix_lifecycle import phases as phases_module
from bcbench.operations.bc_operations import (
    ProjectBuildEvidence,
    ProjectPublicationEvidence,
    TestSuiteEvidence,
)
from bcbench.operations.test_execution import TestCaseResult, TestExpectation, TestIdentity, TestOutcome, TestRunSummary
from bcbench.types import ContainerConfig


def _container() -> ContainerConfig:
    return ContainerConfig(name="bc", username="user", password="pass", company="CRONUS")


def test_project_publisher_exposes_task9_contract() -> None:
    parameters = signature(ProjectPublisher.build_and_publish).parameters
    hints = get_type_hints(ProjectPublisher.build_and_publish)

    assert tuple(parameters) == ("self", "repo_path", "project_paths")
    assert hints == {
        "repo_path": Path,
        "project_paths": tuple[str, ...],
        "return": tuple[Path, ...],
    }


def test_exact_test_runner_exposes_task9_contract() -> None:
    parameters = signature(ExactTestRunner.run).parameters
    hints = get_type_hints(ExactTestRunner.run)

    assert tuple(parameters) == ("self", "tests", "expectation", "repo_path")
    assert hints == {
        "tests": tuple[TestEntry, ...],
        "expectation": TestExpectation,
        "repo_path": Path,
        "return": TestRunSummary,
    }


def test_default_project_publisher_supports_contract_and_evidence(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "src" / "App"
    project.mkdir(parents=True)
    (project / "app.json").write_text(
        '{"id":"11111111-1111-1111-1111-111111111111","name":"App","publisher":"BCBench","version":"1.0.0.0"}',
        encoding="utf-8",
    )
    package = project / "output" / "App.app"
    package.parent.mkdir()
    package.write_bytes(b"app")
    evidence_root = tmp_path / "raw-evidence"
    evidence_root.mkdir()
    command_path = evidence_root / "command.json"
    stdout_path = evidence_root / "stdout.txt"
    stderr_path = evidence_root / "stderr.txt"
    diagnostics_path = evidence_root / "publication.json"
    for path in (command_path, stdout_path, stderr_path, diagnostics_path):
        path.write_text(path.name, encoding="utf-8")
    publication_evidence = ProjectPublicationEvidence(
        (
            ProjectBuildEvidence(
                project_path="src/App",
                command_path=command_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                diagnostics_path=diagnostics_path,
                package_path=package,
                package_hash="a" * 64,
            ),
        )
    )

    def build_with_evidence(
        repo_path: Path,
        project_paths: list[str],
        container: ContainerConfig,
        version: str,
        evidence_directory: Path,
    ) -> ProjectPublicationEvidence:
        assert repo_path == tmp_path
        assert project_paths == ["src/App"]
        assert container == _container()
        assert version == "27.0"
        assert evidence_directory.is_dir()
        return publication_evidence

    monkeypatch.setattr(phases_module, "build_and_publish_projects_with_evidence", build_with_evidence)
    publisher = DefaultProjectPublisher(_container(), "27.0")

    package_paths = publisher.build_and_publish(tmp_path, ("src/App",))
    publication = publisher.build_and_publish_with_evidence(
        tmp_path,
        ("src/App",),
        tmp_path / "phase-evidence",
    )

    assert package_paths == (package,)
    assert publication.package_paths == (package,)
    assert publication.evidence_paths == (command_path, stdout_path, stderr_path, diagnostics_path)


def test_default_exact_test_runner_supports_contract_and_evidence(monkeypatch, tmp_path: Path) -> None:
    test = TestEntry(codeunitID=50100, functionName=frozenset({"Regression"}))
    identity = TestIdentity(50100, "Regression")
    summary = TestRunSummary(
        requested=(identity,),
        discovered=(identity,),
        results=(TestCaseResult(identity, TestOutcome.PASS),),
    )
    evidence_root = tmp_path / "raw-evidence"
    evidence_root.mkdir()
    command_path = evidence_root / "command.json"
    stdout_path = evidence_root / "stdout.txt"
    stderr_path = evidence_root / "stderr.txt"
    discovery_path = evidence_root / "discovery.json"
    junit_path = evidence_root / "results.xml"
    for path in (command_path, stdout_path, stderr_path, discovery_path, junit_path):
        path.write_text(path.name, encoding="utf-8")
    suite_evidence = TestSuiteEvidence(
        summary=summary,
        command_path=command_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        discovery_paths=(discovery_path,),
        junit_paths=(junit_path,),
    )

    def run_with_evidence(
        tests: list[TestEntry],
        expectation: TestExpectation,
        container: ContainerConfig,
        repo_path: Path,
        evidence_directory: Path,
    ) -> TestSuiteEvidence:
        assert tests == [test]
        assert expectation is TestExpectation.ALL_PASS
        assert container == _container()
        assert repo_path == tmp_path
        assert evidence_directory.is_dir()
        return suite_evidence

    monkeypatch.setattr(phases_module, "run_test_suite_with_evidence", run_with_evidence)
    runner = DefaultExactTestRunner(_container())

    returned_summary = runner.run((test,), TestExpectation.ALL_PASS, tmp_path)
    returned_evidence = runner.run_with_evidence(
        (test,),
        TestExpectation.ALL_PASS,
        tmp_path,
        tmp_path / "phase-evidence",
    )

    assert returned_summary is summary
    assert returned_evidence is suite_evidence


def test_benchmark_fix_exposes_four_logical_arguments() -> None:
    parameters = signature(BugFixPhaseRunner.run_benchmark_fix).parameters

    assert tuple(parameters) == (
        "self",
        "submission",
        "sf",
        "benchmark_patch",
        "benchmark_tests",
    )
