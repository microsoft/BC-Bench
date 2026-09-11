import json
import re
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from xml.etree.ElementTree import ParseError

import pytest

from bcbench.config import get_config
from bcbench.dataset import TestEntry
from bcbench.exceptions import TestExecutionError, TestExecutionFailureKind, TestExecutionTimeoutExpired, TestInfrastructureError
from bcbench.operations import bc_operations
from bcbench.operations.test_execution import TestCaseResult, TestExpectation, TestIdentity, TestOutcome, TestRunSummary
from bcbench.types import ContainerConfig
from tests.conftest import create_evaluation_context


def make_summary(*outcomes: TestOutcome) -> TestRunSummary:
    identities = tuple(TestIdentity(50100, f"Test{index}") for index in range(len(outcomes)))
    return TestRunSummary(
        requested=identities,
        discovered=identities,
        results=tuple(TestCaseResult(identity, outcome) for identity, outcome in zip(identities, outcomes, strict=True)),
    )


def write_discovery(evidence_dir: Path, codeunit_id: int, function_names: list[str]) -> None:
    (evidence_dir / f"discovery-{codeunit_id}.json").write_text(
        json.dumps({"codeunitID": codeunit_id, "functionName": function_names}),
        encoding="utf-8",
    )


def write_results(evidence_dir: Path, codeunit_id: int, testcases: str) -> None:
    (evidence_dir / f"results-{codeunit_id}.xml").write_text(
        f"<testsuite>{testcases}</testsuite>",
        encoding="utf-8",
    )


def evidence_path_from_command(command: str) -> Path:
    match = re.search(r"-evidenceDirectory '((?:''|[^'])*)'", command)
    assert match is not None
    return Path(match.group(1).replace("''", "'"))


def entries_json_from_command(command: str) -> str:
    match = re.search(r"\$testEntries = '((?:''|[^'])*)' \| ConvertFrom-Json", command)
    assert match is not None
    return match.group(1).replace("''", "'")


@pytest.fixture
def container(tmp_path: Path) -> ContainerConfig:
    return create_evaluation_context(tmp_path).container


def test_test_execution_enum_values():
    assert TestExecutionFailureKind.SELECTION_EVIDENCE == "selection-evidence"
    assert TestExecutionFailureKind.OUTCOME == "outcome"
    assert TestExpectation.ALL_PASS == "all-pass"
    assert TestExpectation.ALL_FAIL == "all-fail"
    assert TestExpectation.ANY_FAIL == "any-fail"
    assert TestOutcome.PASS == "Pass"
    assert TestOutcome.FAIL == "Fail"
    assert TestOutcome.SKIP == "Skip"


def test_operations_exports_public_test_execution_types():
    from bcbench.operations import TestExpectation as ExportedExpectation
    from bcbench.operations import TestRunSummary as ExportedSummary

    assert ExportedExpectation is TestExpectation
    assert ExportedSummary is TestRunSummary


def test_summary_is_immutable_and_exposes_counts_and_executed_identities():
    first = TestIdentity(50100, "First")
    second = TestIdentity(50100, "Second")
    summary = TestRunSummary(
        requested=(second, first),
        discovered=(first,),
        results=(TestCaseResult(first, TestOutcome.PASS),),
    )

    assert sorted(summary.requested) == [first, second]
    assert summary.executed == (first,)
    assert summary.requested_count == 2
    assert summary.discovered_count == 1
    assert summary.executed_count == 1
    with pytest.raises(FrozenInstanceError):
        summary.requested = ()  # ty: ignore[invalid-assignment]


def test_summary_copies_caller_owned_lists():
    identity = TestIdentity(50100, "Stable")
    result = TestCaseResult(identity, TestOutcome.PASS)
    requested = [identity]
    discovered = [identity]
    results = [result]

    summary = TestRunSummary(requested=requested, discovered=discovered, results=results)
    requested.clear()
    discovered.append(TestIdentity(50100, "Added"))
    results.clear()

    assert summary.requested == (identity,)
    assert summary.discovered == (identity,)
    assert summary.results == (result,)


def test_combine_concatenates_summary_evidence():
    first = TestIdentity(50100, "First")
    second = TestIdentity(50200, "Second")
    first_summary = TestRunSummary((first,), (first,), (TestCaseResult(first, TestOutcome.PASS),))
    second_summary = TestRunSummary((second,), (second,), (TestCaseResult(second, TestOutcome.FAIL),))

    combined = TestRunSummary.combine([first_summary, second_summary])

    assert combined == TestRunSummary(
        requested=(first, second),
        discovered=(first, second),
        results=(
            TestCaseResult(first, TestOutcome.PASS),
            TestCaseResult(second, TestOutcome.FAIL),
        ),
    )


def test_exact_all_fail_is_accepted():
    make_summary(TestOutcome.FAIL, TestOutcome.FAIL).require(TestExpectation.ALL_FAIL)


def test_mixed_outcomes_reject_all_fail():
    summary = make_summary(TestOutcome.FAIL, TestOutcome.PASS)

    with pytest.raises(TestExecutionError) as error:
        summary.require(TestExpectation.ALL_FAIL)

    assert error.value.reason == "Expected every test to fail, but 1 did not."
    assert error.value.failure_kind is TestExecutionFailureKind.OUTCOME
    assert error.value.summary is summary


def test_all_pass_is_accepted():
    make_summary(TestOutcome.PASS, TestOutcome.PASS).require(TestExpectation.ALL_PASS)


def test_any_fail_is_accepted_with_mixed_outcomes():
    make_summary(TestOutcome.PASS, TestOutcome.FAIL).require(TestExpectation.ANY_FAIL)


@pytest.mark.parametrize(
    ("expectation", "outcomes"),
    [
        ("all-pass", (TestOutcome.PASS,)),
        ("all-fail", (TestOutcome.FAIL,)),
        ("any-fail", (TestOutcome.PASS, TestOutcome.FAIL)),
    ],
)
def test_valid_expectation_strings_are_accepted(expectation: str, outcomes: tuple[TestOutcome, ...]):
    make_summary(*outcomes).require(expectation)


def test_invalid_expectation_string_is_rejected():
    with pytest.raises(ValueError, match="not-an-expectation"):
        make_summary(TestOutcome.FAIL).require("not-an-expectation")


def test_mixed_outcomes_reject_all_pass():
    summary = make_summary(TestOutcome.PASS, TestOutcome.FAIL)

    with pytest.raises(TestExecutionError) as error:
        summary.require(TestExpectation.ALL_PASS)

    assert error.value.reason == "Expected every test to pass, but 1 did not."
    assert error.value.summary is summary


def test_any_fail_rejects_all_passed():
    summary = make_summary(TestOutcome.PASS, TestOutcome.PASS)

    with pytest.raises(TestExecutionError) as error:
        summary.require(TestExpectation.ANY_FAIL)

    assert error.value.reason == "Expected at least one test to fail."
    assert error.value.summary is summary


def test_empty_requested_tests_are_rejected_with_summary_context():
    summary = TestRunSummary(requested=(), discovered=(), results=())

    with pytest.raises(TestExecutionError) as error:
        summary.require(TestExpectation.ALL_PASS)

    assert error.value.reason == "No tests were requested."
    assert error.value.failure_kind is TestExecutionFailureKind.SELECTION_EVIDENCE
    assert error.value.summary is summary


def test_missing_discovery_uses_multiset_counts():
    identity = TestIdentity(50100, "Repeated")
    summary = TestRunSummary(
        requested=(identity, identity),
        discovered=(identity,),
        results=(
            TestCaseResult(identity, TestOutcome.PASS),
            TestCaseResult(identity, TestOutcome.PASS),
        ),
    )

    with pytest.raises(TestExecutionError) as error:
        summary.require(TestExpectation.ALL_PASS)

    assert error.value.reason == "Discovery evidence mismatch: missing 1, unexpected 0."
    assert error.value.failure_kind is TestExecutionFailureKind.SELECTION_EVIDENCE


@pytest.mark.parametrize(
    "unexpected",
    [
        TestIdentity(50100, "Requested"),
        TestIdentity(50100, "Different"),
    ],
)
def test_unexpected_discovery_identity_or_duplicate_is_rejected(unexpected: TestIdentity):
    requested = TestIdentity(50100, "Requested")
    summary = TestRunSummary(
        requested=(requested,),
        discovered=(requested, unexpected),
        results=(TestCaseResult(requested, TestOutcome.PASS),),
    )

    with pytest.raises(TestExecutionError) as error:
        summary.require(TestExpectation.ALL_PASS)

    assert error.value.reason == "Discovery evidence mismatch: missing 0, unexpected 1."
    assert error.value.failure_kind is TestExecutionFailureKind.SELECTION_EVIDENCE


def test_missing_execution_is_rejected():
    identity = TestIdentity(50100, "Missing")
    summary = TestRunSummary(requested=(identity,), discovered=(identity,), results=())

    with pytest.raises(TestExecutionError) as error:
        summary.require(TestExpectation.ALL_PASS)

    assert error.value.reason == "Execution evidence mismatch: missing 1, unexpected 0."
    assert error.value.failure_kind is TestExecutionFailureKind.SELECTION_EVIDENCE


def test_extra_execution_is_rejected():
    requested = TestIdentity(50100, "Requested")
    extra = TestIdentity(50100, "Extra")
    summary = TestRunSummary(
        requested=(requested,),
        discovered=(requested,),
        results=(
            TestCaseResult(requested, TestOutcome.PASS),
            TestCaseResult(extra, TestOutcome.PASS),
        ),
    )

    with pytest.raises(TestExecutionError) as error:
        summary.require(TestExpectation.ALL_PASS)

    assert error.value.reason == "Execution evidence mismatch: missing 0, unexpected 1."
    assert error.value.failure_kind is TestExecutionFailureKind.SELECTION_EVIDENCE


def test_duplicate_execution_is_rejected():
    identity = TestIdentity(50100, "Repeated")
    result = TestCaseResult(identity, TestOutcome.PASS)
    summary = TestRunSummary(
        requested=(identity,),
        discovered=(identity,),
        results=(result, result),
    )

    with pytest.raises(TestExecutionError) as error:
        summary.require(TestExpectation.ALL_PASS)

    assert error.value.reason == "Execution evidence mismatch: missing 0, unexpected 1."
    assert error.value.failure_kind is TestExecutionFailureKind.SELECTION_EVIDENCE


def test_skipped_execution_is_rejected():
    identity = TestIdentity(50100, "Skipped")
    summary = TestRunSummary(
        requested=(identity,),
        discovered=(identity,),
        results=(TestCaseResult(identity, TestOutcome.SKIP),),
    )

    with pytest.raises(TestExecutionError) as error:
        summary.require(TestExpectation.ALL_FAIL)

    assert error.value.reason == "Skipped tests are not allowed: 1."
    assert error.value.failure_kind is TestExecutionFailureKind.SELECTION_EVIDENCE


def test_load_test_run_summary_reads_discovery_and_outcomes(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    write_discovery(tmp_path, 50100, ["Passes", "Fails", "Skips"])
    write_results(
        tmp_path,
        50100,
        """
        <testcase name="Passes" />
        <testcase name="Fails"><failure /></testcase>
        <testcase name="Skips"><skipped /></testcase>
        """,
    )
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"Passes", "Fails", "Skips"}))]

    summary = load_test_run_summary(tmp_path, entries)

    assert set(summary.discovered) == {
        TestIdentity(50100, "Passes"),
        TestIdentity(50100, "Fails"),
        TestIdentity(50100, "Skips"),
    }
    assert summary.results == (
        TestCaseResult(TestIdentity(50100, "Passes"), TestOutcome.PASS),
        TestCaseResult(TestIdentity(50100, "Fails"), TestOutcome.FAIL),
        TestCaseResult(TestIdentity(50100, "Skips"), TestOutcome.SKIP),
    )


def test_all_pass_rejects_plain_junit_error_evidence(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    results_path = tmp_path / "results-50100.xml"
    write_discovery(tmp_path, 50100, ["InfrastructureError"])
    write_results(tmp_path, 50100, '<testcase name="InfrastructureError"><error /></testcase>')
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"InfrastructureError"}))]

    with pytest.raises(ValueError, match="JUnit error evidence") as error:
        load_test_run_summary(tmp_path, entries).require(TestExpectation.ALL_PASS)

    assert "50100" in str(error.value)
    assert "InfrastructureError" in str(error.value)
    assert str(results_path) in str(error.value)


def test_all_pass_rejects_namespaced_junit_error_evidence(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    results_path = tmp_path / "results-50100.xml"
    write_discovery(tmp_path, 50100, ["NamespacedInfrastructureError"])
    write_results(
        tmp_path,
        50100,
        '<testcase name="NamespacedInfrastructureError"><junit:error xmlns:junit="urn:junit" /></testcase>',
    )
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"NamespacedInfrastructureError"}))]

    with pytest.raises(ValueError, match="JUnit error evidence") as error:
        load_test_run_summary(tmp_path, entries).require(TestExpectation.ALL_PASS)

    assert "50100" in str(error.value)
    assert "NamespacedInfrastructureError" in str(error.value)
    assert str(results_path) in str(error.value)


def test_junit_testcase_requires_name_attribute(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    results_path = tmp_path / "results-50100.xml"
    write_discovery(tmp_path, 50100, ["MissingName"])
    write_results(tmp_path, 50100, "<testcase />")
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"MissingName"}))]

    with pytest.raises(ValueError, match="JUnit testcase is missing required name attribute") as error:
        load_test_run_summary(tmp_path, entries)

    assert str(results_path) in str(error.value)


def test_same_function_name_in_two_codeunits_remains_distinct(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    for codeunit_id in (50100, 50200):
        write_discovery(tmp_path, codeunit_id, ["SameName"])
        write_results(tmp_path, codeunit_id, '<testcase name="SameName" />')
    entries = [
        TestEntry(codeunitID=50100, functionName=frozenset({"SameName"})),
        TestEntry(codeunitID=50200, functionName=frozenset({"SameName"})),
    ]

    summary = load_test_run_summary(tmp_path, entries)

    identities = (
        TestIdentity(50100, "SameName"),
        TestIdentity(50200, "SameName"),
    )
    assert summary.requested == identities
    assert summary.discovered == identities
    assert summary.executed == identities


def test_missing_discovery_file_remains_absent(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    write_results(tmp_path, 50100, '<testcase name="MissingDiscovery" />')
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"MissingDiscovery"}))]

    summary = load_test_run_summary(tmp_path, entries)

    assert summary.discovered == ()
    with pytest.raises(TestExecutionError) as error:
        summary.require(TestExpectation.ALL_PASS)
    assert error.value.reason == "Discovery evidence mismatch: missing 1, unexpected 0."


def test_missing_results_file_raises_file_not_found_error(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    write_discovery(tmp_path, 50100, ["MissingExecution"])
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"MissingExecution"}))]
    results_path = tmp_path / "results-50100.xml"

    with pytest.raises(FileNotFoundError) as error:
        load_test_run_summary(tmp_path, entries)

    assert str(results_path) in str(error.value)
    assert "50100" in str(error.value)


def test_discovery_payload_must_be_an_object(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    discovery_path = tmp_path / "discovery-50100.json"
    discovery_path.write_text(json.dumps(["NotAnObject"]), encoding="utf-8")
    write_results(tmp_path, 50100, '<testcase name="Invalid" />')
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"Invalid"}))]

    with pytest.raises(ValueError, match="object") as error:
        load_test_run_summary(tmp_path, entries)

    assert str(discovery_path) in str(error.value)


def test_discovery_codeunit_id_must_match_expected_codeunit(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    discovery_path = tmp_path / "discovery-50100.json"
    discovery_path.write_text(json.dumps({"codeunitID": 50200, "functionName": ["WrongCodeunit"]}), encoding="utf-8")
    write_results(tmp_path, 50100, '<testcase name="WrongCodeunit" />')
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"WrongCodeunit"}))]

    with pytest.raises(ValueError, match="codeunitID") as error:
        load_test_run_summary(tmp_path, entries)

    assert str(discovery_path) in str(error.value)
    assert "50100" in str(error.value)
    assert "50200" in str(error.value)


def test_discovery_function_names_must_be_a_list(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    discovery_path = tmp_path / "discovery-50100.json"
    discovery_path.write_text(json.dumps({"codeunitID": 50100, "functionName": "Scalar"}), encoding="utf-8")
    write_results(tmp_path, 50100, '<testcase name="Scalar" />')
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"Scalar"}))]

    with pytest.raises(ValueError, match="functionName") as error:
        load_test_run_summary(tmp_path, entries)

    assert str(discovery_path) in str(error.value)


def test_discovery_function_names_must_contain_only_strings(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    discovery_path = tmp_path / "discovery-50100.json"
    discovery_path.write_text(json.dumps({"codeunitID": 50100, "functionName": ["Valid", 42]}), encoding="utf-8")
    write_results(tmp_path, 50100, '<testcase name="Valid" />')
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"Valid"}))]

    with pytest.raises(ValueError, match="functionName") as error:
        load_test_run_summary(tmp_path, entries)

    assert str(discovery_path) in str(error.value)


def test_malformed_xml_propagates_parse_error(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    write_discovery(tmp_path, 50100, ["Malformed"])
    (tmp_path / "results-50100.xml").write_text("<testsuite>", encoding="utf-8")
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"Malformed"}))]

    with pytest.raises(ParseError):
        load_test_run_summary(tmp_path, entries)


def test_malformed_json_propagates_decode_error(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    (tmp_path / "discovery-50100.json").write_text("{", encoding="utf-8")
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"Malformed"}))]

    with pytest.raises(json.JSONDecodeError):
        load_test_run_summary(tmp_path, entries)


def test_discovery_json_accepts_utf8_bom(tmp_path: Path):
    from bcbench.operations.test_execution import load_test_run_summary

    discovery = json.dumps({"codeunitID": 50100, "functionName": ["WithBom"]}).encode()
    (tmp_path / "discovery-50100.json").write_bytes(b"\xef\xbb\xbf" + discovery)
    write_results(tmp_path, 50100, '<testcase name="WithBom" />')
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"WithBom"}))]

    summary = load_test_run_summary(tmp_path, entries)

    summary.require(TestExpectation.ALL_PASS)


def test_normalize_test_entries_groups_codeunits_and_unions_functions_deterministically():
    entries = [
        TestEntry(codeunitID=200, functionName=frozenset({"Zulu"})),
        TestEntry(codeunitID=100, functionName=frozenset({"Beta", "Alpha"})),
        TestEntry(codeunitID=100, functionName=frozenset({"Gamma", "Alpha"})),
    ]

    normalized = bc_operations._normalize_test_entries(entries)

    assert normalized == [
        TestEntry(codeunitID=100, functionName=frozenset({"Alpha", "Beta", "Gamma"})),
        TestEntry(codeunitID=200, functionName=frozenset({"Zulu"})),
    ]


def test_run_test_suite_serializes_exact_json_and_returns_parsed_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, container: ContainerConfig):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        evidence_path = evidence_path_from_command(command[-1])
        assert evidence_path.parent == repo_path
        assert evidence_path.name.startswith(".bcbench-test-evidence-")
        write_discovery(evidence_path, 100, ["Alpha", "Beta", "Gamma"])
        write_results(evidence_path, 100, '<testcase name="Alpha" /><testcase name="Beta" /><testcase name="Gamma" />')
        write_discovery(evidence_path, 200, ["Zulu"])
        write_results(evidence_path, 200, '<testcase name="Zulu" />')
        return subprocess.CompletedProcess(command, returncode=0, stdout="test output", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    entries = [
        TestEntry(codeunitID=200, functionName=frozenset({"Zulu"})),
        TestEntry(codeunitID=100, functionName=frozenset({"Beta", "Alpha"})),
        TestEntry(codeunitID=100, functionName=frozenset({"Gamma"})),
    ]

    summary = bc_operations.run_test_suite(entries, TestExpectation.ALL_PASS, container, repo_path)

    command, kwargs = calls[0]
    assert entries_json_from_command(command[-1]) == ('[{"codeunitID":100,"functionName":["Alpha","Beta","Gamma"]},{"codeunitID":200,"functionName":["Zulu"]}]')
    assert kwargs["cwd"] == repo_path
    assert kwargs["check"] is False
    assert summary.requested == (
        TestIdentity(100, "Alpha"),
        TestIdentity(100, "Beta"),
        TestIdentity(100, "Gamma"),
        TestIdentity(200, "Zulu"),
    )
    assert all(result.outcome is TestOutcome.PASS for result in summary.results)


def test_expected_failed_tests_do_not_depend_on_subprocess_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, container: ContainerConfig):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        evidence_path = evidence_path_from_command(command[-1])
        write_discovery(evidence_path, 50100, ["RegressionTest"])
        write_results(evidence_path, 50100, '<testcase name="RegressionTest"><failure /></testcase>')
        return subprocess.CompletedProcess(command, returncode=0, stdout="tests failed as expected", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"RegressionTest"}))]

    summary = bc_operations.run_test_suite(entries, TestExpectation.ANY_FAIL, container, repo_path)

    assert summary.results == (TestCaseResult(TestIdentity(50100, "RegressionTest"), TestOutcome.FAIL),)


def test_expectation_failure_preserves_powershell_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: ContainerConfig,
):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    stdout = """\
BcContainerHelper version 6.1.11
Codeunit 50100 Regression Tests
    Testfunction RegressionTest Failure (0.25 seconds)
      Error:
        Assert.AreEqual failed. Expected:<1>. Actual:<2>. Values differ.
"""

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        evidence_path = evidence_path_from_command(command[-1])
        write_discovery(evidence_path, 50100, ["RegressionTest"])
        write_results(evidence_path, 50100, '<testcase name="RegressionTest"><failure /></testcase>')
        return subprocess.CompletedProcess(command, returncode=0, stdout=stdout, stderr="PowerShell diagnostic")

    monkeypatch.setattr(subprocess, "run", run)
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"RegressionTest"}))]

    with pytest.raises(TestExecutionError) as error:
        bc_operations.run_test_suite(entries, TestExpectation.ALL_PASS, container, repo_path)

    assert not isinstance(error.value, TestInfrastructureError)
    assert error.value.failure_kind is TestExecutionFailureKind.OUTCOME
    assert error.value.reason == "Expected every test to pass, but 1 did not."
    assert error.value.stdout == stdout
    assert error.value.stderr == "PowerShell diagnostic"
    assert error.value.summary is not None
    assert error.value.summary.results == (TestCaseResult(TestIdentity(50100, "RegressionTest"), TestOutcome.FAIL),)
    assert "Testfunction RegressionTest Failure" in str(error.value)
    assert "Assert.AreEqual failed" in str(error.value)


def test_selection_failure_preserves_powershell_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: ContainerConfig,
):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        evidence_path = evidence_path_from_command(command[-1])
        write_discovery(evidence_path, 50100, [])
        write_results(evidence_path, 50100, "")
        return subprocess.CompletedProcess(command, returncode=0, stdout="selection output", stderr="selection diagnostic")

    monkeypatch.setattr(subprocess, "run", run)
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"RegressionTest"}))]

    with pytest.raises(TestExecutionError) as error:
        bc_operations.run_test_suite(entries, TestExpectation.ALL_PASS, container, repo_path)

    assert error.value.failure_kind is TestExecutionFailureKind.SELECTION_EVIDENCE
    assert error.value.reason == "Discovery evidence mismatch: missing 1, unexpected 0."
    assert error.value.stdout == "selection output"
    assert error.value.stderr == "selection diagnostic"


def test_nonzero_subprocess_with_valid_partial_summary_is_infrastructure_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: ContainerConfig,
):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        evidence_path = evidence_path_from_command(command[-1])
        write_discovery(evidence_path, 50100, ["First", "Second"])
        write_results(evidence_path, 50100, '<testcase name="First" />')
        return subprocess.CompletedProcess(command, returncode=1, stdout="partial output", stderr="infrastructure error")

    monkeypatch.setattr(subprocess, "run", run)
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"First", "Second"}))]

    with pytest.raises(TestInfrastructureError) as error:
        bc_operations.run_test_suite(entries, TestExpectation.ALL_PASS, container, repo_path)

    assert error.value.reason == "Business Central test execution failed before evidence validation"
    assert error.value.summary is not None
    assert error.value.summary.executed == (TestIdentity(50100, "First"),)
    assert error.value.stdout == "partial output"
    assert error.value.stderr == "infrastructure error"
    assert "Test infrastructure failed" in str(error.value)
    assert "partial output" in str(error.value)
    assert "infrastructure error" in str(error.value)


@pytest.mark.parametrize("invalid_evidence", ["malformed-json", "malformed-xml", "missing-junit", "os-error"])
def test_invalid_test_evidence_is_wrapped(
    invalid_evidence: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: ContainerConfig,
):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        evidence_path = evidence_path_from_command(command[-1])
        if invalid_evidence == "malformed-json":
            (evidence_path / "discovery-50100.json").write_text("{", encoding="utf-8")
            write_results(evidence_path, 50100, '<testcase name="RegressionTest" />')
        elif invalid_evidence == "malformed-xml":
            write_discovery(evidence_path, 50100, ["RegressionTest"])
            (evidence_path / "results-50100.xml").write_text("<testsuite>", encoding="utf-8")
        elif invalid_evidence == "missing-junit":
            write_discovery(evidence_path, 50100, ["RegressionTest"])
        return subprocess.CompletedProcess(command, returncode=0, stdout="output", stderr="error output")

    monkeypatch.setattr(subprocess, "run", run)
    if invalid_evidence == "os-error":
        monkeypatch.setattr(bc_operations, "load_test_run_summary", lambda *_args: (_ for _ in ()).throw(OSError("read failed")), raising=False)
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"RegressionTest"}))]

    with pytest.raises(TestInfrastructureError) as error:
        bc_operations.run_test_suite(entries, TestExpectation.ALL_PASS, container, repo_path)

    assert error.value.reason.startswith("Invalid test evidence: ")
    assert error.value.expectation is TestExpectation.ALL_PASS
    assert error.value.stdout == "output"
    assert error.value.stderr == "error output"


def test_missing_junit_testcase_name_is_wrapped_as_invalid_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: ContainerConfig,
):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        evidence_path = evidence_path_from_command(command[-1])
        write_discovery(evidence_path, 50100, ["MissingName"])
        write_results(evidence_path, 50100, "<testcase />")
        return subprocess.CompletedProcess(command, returncode=0, stdout="output", stderr="error output")

    monkeypatch.setattr(subprocess, "run", run)
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"MissingName"}))]

    with pytest.raises(TestInfrastructureError) as error:
        bc_operations.run_test_suite(entries, TestExpectation.ALL_PASS, container, repo_path)

    assert error.value.reason.startswith("Invalid test evidence: JUnit testcase is missing required name attribute")
    assert "results-50100.xml" in error.value.reason
    assert isinstance(error.value.__cause__, ValueError)


def test_subprocess_launch_oserror_is_wrapped_as_infrastructure_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: ContainerConfig,
):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    launch_error = FileNotFoundError(2, "No such file or directory", "pwsh")
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(launch_error))
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"RegressionTest"}))]

    with pytest.raises(TestInfrastructureError) as error:
        bc_operations.run_test_suite(entries, TestExpectation.ALL_PASS, container, repo_path)

    assert error.value.reason.startswith("Failed to launch Business Central test execution infrastructure: ")
    assert "pwsh" in error.value.reason
    assert error.value.expectation is TestExpectation.ALL_PASS
    assert error.value.summary is None
    assert error.value.__cause__ is launch_error


def test_run_test_suite_wraps_timeout_as_infrastructure_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: ContainerConfig,
):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            command,
            timeout=123,
            output="partial test output",
            stderr="timeout diagnostic",
        )

    monkeypatch.setattr(subprocess, "run", run)
    entries = [TestEntry(codeunitID=50100, functionName=frozenset({"RegressionTest"}))]

    with pytest.raises(TestInfrastructureError) as error:
        bc_operations.run_test_suite(entries, TestExpectation.ALL_PASS, container, repo_path)

    assert error.value.expectation is TestExpectation.ALL_PASS
    assert error.value.reason == f"Business Central test execution timed out after {get_config().timeout.test_execution} seconds"
    assert error.value.stdout == "partial test output"
    assert error.value.stderr == "timeout diagnostic"
    assert isinstance(error.value.__cause__, TestExecutionTimeoutExpired)
    assert error.value.__cause__.tests == '[{"codeunitID":50100,"functionName":["RegressionTest"]}]'


def test_run_tests_combines_fail_to_pass_and_pass_to_pass_summaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, container: ContainerConfig):
    repo_path = tmp_path / "repo"
    first = TestEntry(codeunitID=50100, functionName=frozenset({"First"}))
    second = TestEntry(codeunitID=50200, functionName=frozenset({"Second"}))
    entry = SimpleNamespace(fail_to_pass=[first], pass_to_pass=[second])
    calls: list[tuple[list[TestEntry], TestExpectation, ContainerConfig, Path]] = []
    summaries = [
        TestRunSummary((TestIdentity(50100, "First"),), (TestIdentity(50100, "First"),), (TestCaseResult(TestIdentity(50100, "First"), TestOutcome.PASS),)),
        TestRunSummary((TestIdentity(50200, "Second"),), (TestIdentity(50200, "Second"),), (TestCaseResult(TestIdentity(50200, "Second"), TestOutcome.PASS),)),
    ]

    def run_test_suite(
        test_entries: list[TestEntry],
        expectation: TestExpectation,
        actual_container: ContainerConfig,
        actual_repo_path: Path,
    ) -> TestRunSummary:
        calls.append((test_entries, expectation, actual_container, actual_repo_path))
        return summaries[len(calls) - 1]

    monkeypatch.setattr(bc_operations, "run_test_suite", run_test_suite)

    summary = bc_operations.run_tests(entry, container, repo_path)

    assert calls == [
        ([first], TestExpectation.ALL_PASS, container, repo_path),
        ([second], TestExpectation.ALL_PASS, container, repo_path),
    ]
    assert summary == TestRunSummary.combine(summaries)


def test_run_tests_rejects_empty_benchmark_selection_as_infrastructure_failure(tmp_path: Path, container: ContainerConfig):
    entry = SimpleNamespace(fail_to_pass=[], pass_to_pass=[])

    with pytest.raises(TestInfrastructureError) as error:
        bc_operations.run_tests(entry, container, tmp_path)

    assert error.value.reason == "No tests were requested."
    assert error.value.expectation is TestExpectation.ALL_PASS


@pytest.mark.parametrize("missing_evidence", ["discovery", "execution"])
def test_run_tests_treats_missing_hidden_benchmark_evidence_as_infrastructure_failure(
    missing_evidence: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: ContainerConfig,
):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        evidence_path = evidence_path_from_command(command[-1])
        write_discovery(evidence_path, 50100, [] if missing_evidence == "discovery" else ["RegressionTest"])
        write_results(evidence_path, 50100, "")
        return subprocess.CompletedProcess(command, returncode=0, stdout="hidden output", stderr="hidden diagnostic")

    monkeypatch.setattr(subprocess, "run", run)
    entry = SimpleNamespace(
        fail_to_pass=[TestEntry(codeunitID=50100, functionName=frozenset({"RegressionTest"}))],
        pass_to_pass=[],
    )

    with pytest.raises(TestInfrastructureError) as error:
        bc_operations.run_tests(entry, container, repo_path)

    expected_prefix = "Discovery" if missing_evidence == "discovery" else "Execution"
    assert error.value.reason.startswith(f"{expected_prefix} evidence mismatch: missing 1")
    assert error.value.stdout == "hidden output"
    assert error.value.stderr == "hidden diagnostic"
    assert error.value.summary is not None


def test_run_tests_keeps_hidden_assertion_failure_as_model_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container: ContainerConfig,
):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        evidence_path = evidence_path_from_command(command[-1])
        write_discovery(evidence_path, 50100, ["RegressionTest"])
        write_results(evidence_path, 50100, '<testcase name="RegressionTest"><failure /></testcase>')
        return subprocess.CompletedProcess(command, returncode=0, stdout="assertion output", stderr="assertion diagnostic")

    monkeypatch.setattr(subprocess, "run", run)
    entry = SimpleNamespace(
        fail_to_pass=[TestEntry(codeunitID=50100, functionName=frozenset({"RegressionTest"}))],
        pass_to_pass=[],
    )

    with pytest.raises(TestExecutionError) as error:
        bc_operations.run_tests(entry, container, repo_path)

    assert error.value.failure_kind is TestExecutionFailureKind.OUTCOME
    assert error.value.reason == "Expected every test to pass, but 1 did not."
    assert error.value.stdout == "assertion output"
    assert error.value.stderr == "assertion diagnostic"
