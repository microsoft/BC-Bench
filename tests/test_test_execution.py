import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from xml.etree.ElementTree import ParseError

import pytest

from bcbench.dataset import TestEntry
from bcbench.exceptions import TestExecutionError
from bcbench.operations.test_execution import TestCaseResult, TestExpectation, TestIdentity, TestOutcome, TestRunSummary


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


def test_test_execution_enum_values():
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


def test_missing_execution_is_rejected():
    identity = TestIdentity(50100, "Missing")
    summary = TestRunSummary(requested=(identity,), discovered=(identity,), results=())

    with pytest.raises(TestExecutionError) as error:
        summary.require(TestExpectation.ALL_PASS)

    assert error.value.reason == "Execution evidence mismatch: missing 1, unexpected 0."


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
