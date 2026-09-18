import json
from pathlib import Path

import pytest

from bcbench.dataset import TestEntry
from bcbench.evaluate.bugfix_lifecycle.phases import classify_phase_error
from bcbench.evaluate.bugfix_lifecycle.rehearsal import RehearsalFault, inject_test_evidence_fault
from bcbench.exceptions import TestExecutionError, TestInfrastructureError
from bcbench.operations.bc_operations import require_test_evidence
from bcbench.operations.test_execution import TestExpectation
from bcbench.results.bugfix import BugFixPhaseStatus


def _valid_evidence(directory: Path) -> tuple[TestEntry, ...]:
    tests = (TestEntry(codeunitID=50199, functionName=frozenset({"RehearsalProbe"})),)
    (directory / "discovery-50199.json").write_text(json.dumps({"codeunitID": 50199, "functionName": ["RehearsalProbe"]}), encoding="utf-8")
    (directory / "results-50199.xml").write_text('<testsuite><testcase name="RehearsalProbe"/></testsuite>', encoding="utf-8")
    return tests


@pytest.mark.parametrize("fault", [RehearsalFault.MISSING_JUNIT, RehearsalFault.DUPLICATE_DISCOVERY, RehearsalFault.DUPLICATE_EXECUTION])
def test_fault_changes_real_test_evidence_and_uses_production_classification(tmp_path: Path, fault: RehearsalFault) -> None:
    tests = _valid_evidence(tmp_path)
    discovery = tmp_path / "discovery-50199.json"
    junit = tmp_path / "results-50199.xml"
    require_test_evidence(tmp_path, tests, TestExpectation.ALL_PASS)
    inject_test_evidence_fault(fault, tmp_path, tests)
    with pytest.raises((TestExecutionError, TestInfrastructureError)) as caught:
        require_test_evidence(tmp_path, tests, TestExpectation.ALL_PASS)
    assert classify_phase_error(caught.value) is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    if fault is RehearsalFault.MISSING_JUNIT:
        assert not junit.exists()
    elif fault is RehearsalFault.DUPLICATE_DISCOVERY:
        assert json.loads(discovery.read_text())["functionName"] == ["RehearsalProbe"] * 2
    else:
        assert junit.read_text().count('name="RehearsalProbe"') == 2


def test_evidence_injection_does_not_accept_unrelated_broken_input(tmp_path: Path) -> None:
    with pytest.raises(TestInfrastructureError, match="Invalid test evidence"):
        inject_test_evidence_fault(
            RehearsalFault.DUPLICATE_EXECUTION,
            tmp_path,
            (TestEntry(codeunitID=50199, functionName=frozenset({"RehearsalProbe"})),),
        )


@pytest.mark.parametrize("failure", ["nonzero_exit", "assertion", "malformed", "empty_selection"])
def test_shared_evidence_classifier_preserves_failure_kind(tmp_path: Path, failure: str) -> None:
    tests = _valid_evidence(tmp_path)
    if failure == "assertion":
        (tmp_path / "results-50199.xml").write_text('<testsuite><testcase name="RehearsalProbe"><failure/></testcase></testsuite>', encoding="utf-8")
    elif failure == "malformed":
        (tmp_path / "results-50199.xml").write_text("<invalid", encoding="utf-8")
    elif failure == "empty_selection":
        tests = ()
    with pytest.raises((TestExecutionError, TestInfrastructureError)) as caught:
        require_test_evidence(
            tmp_path,
            tests,
            TestExpectation.ALL_PASS,
            returncode=1 if failure == "nonzero_exit" else 0,
            stdout="fixture stdout",
            stderr="fixture stderr",
        )
    expected = BugFixPhaseStatus.FAILED if failure == "assertion" else BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert classify_phase_error(caught.value) is expected
    assert caught.value.stdout == "fixture stdout"
    assert caught.value.stderr == "fixture stderr"


def test_evidence_injection_refuses_preexisting_test_failure(tmp_path: Path) -> None:
    tests = _valid_evidence(tmp_path)
    junit = tmp_path / "results-50199.xml"
    junit.write_text('<testsuite><testcase name="RehearsalProbe"><failure/></testcase></testsuite>', encoding="utf-8")
    pristine = junit.read_bytes()
    with pytest.raises(TestExecutionError):
        inject_test_evidence_fault(RehearsalFault.MISSING_JUNIT, tmp_path, tests)
    assert junit.read_bytes() == pristine


def test_non_evidence_fault_is_rejected_without_mutation(tmp_path: Path) -> None:
    tests = _valid_evidence(tmp_path)
    pristine = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    with pytest.raises(ValueError, match="Not a test-evidence fault"):
        inject_test_evidence_fault(RehearsalFault.CORRUPT_BACKUP, tmp_path, tests)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == pristine
