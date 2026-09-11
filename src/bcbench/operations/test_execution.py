from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from bcbench.dataset import TestEntry
from bcbench.exceptions import TestExecutionError, TestExecutionFailureKind


class TestExpectation(StrEnum):
    ALL_PASS = "all-pass"
    ALL_FAIL = "all-fail"
    ANY_FAIL = "any-fail"


class TestOutcome(StrEnum):
    PASS = "Pass"
    FAIL = "Fail"
    SKIP = "Skip"


@dataclass(frozen=True, order=True)
class TestIdentity:
    codeunit_id: int
    function_name: str


@dataclass(frozen=True)
class TestCaseResult:
    identity: TestIdentity
    outcome: TestOutcome


@dataclass(frozen=True, init=False)
class TestRunSummary:
    requested: tuple[TestIdentity, ...]
    discovered: tuple[TestIdentity, ...]
    results: tuple[TestCaseResult, ...]

    def __init__(
        self,
        requested: Iterable[TestIdentity],
        discovered: Iterable[TestIdentity],
        results: Iterable[TestCaseResult],
    ) -> None:
        object.__setattr__(self, "requested", requested)
        object.__setattr__(self, "discovered", discovered)
        object.__setattr__(self, "results", results)
        self.__post_init__()

    def __post_init__(self) -> None:
        object.__setattr__(self, "requested", tuple(self.requested))
        object.__setattr__(self, "discovered", tuple(self.discovered))
        object.__setattr__(self, "results", tuple(self.results))

    @property
    def executed(self) -> tuple[TestIdentity, ...]:
        return tuple(result.identity for result in self.results)

    @property
    def requested_count(self) -> int:
        return len(self.requested)

    @property
    def discovered_count(self) -> int:
        return len(self.discovered)

    @property
    def executed_count(self) -> int:
        return len(self.results)

    @classmethod
    def combine(cls, summaries: Iterable[TestRunSummary]) -> TestRunSummary:
        summary_list = tuple(summaries)
        return cls(
            requested=tuple(identity for summary in summary_list for identity in summary.requested),
            discovered=tuple(identity for summary in summary_list for identity in summary.discovered),
            results=tuple(result for summary in summary_list for result in summary.results),
        )

    def require(self, expectation: TestExpectation | str) -> None:
        expectation = TestExpectation(expectation)

        if not self.requested:
            raise TestExecutionError(
                expectation,
                reason="No tests were requested.",
                summary=self,
                failure_kind=TestExecutionFailureKind.SELECTION_EVIDENCE,
            )

        requested = Counter(self.requested)
        discovered = Counter(self.discovered)
        missing_discovered = sum((requested - discovered).values())
        unexpected_discovered = sum((discovered - requested).values())
        if missing_discovered or unexpected_discovered:
            reason = f"Discovery evidence mismatch: missing {missing_discovered}, unexpected {unexpected_discovered}."
            raise TestExecutionError(
                expectation,
                reason=reason,
                summary=self,
                failure_kind=TestExecutionFailureKind.SELECTION_EVIDENCE,
            )

        executed = Counter(self.executed)
        missing_executed = sum((requested - executed).values())
        unexpected_executed = sum((executed - requested).values())
        if missing_executed or unexpected_executed:
            reason = f"Execution evidence mismatch: missing {missing_executed}, unexpected {unexpected_executed}."
            raise TestExecutionError(
                expectation,
                reason=reason,
                summary=self,
                failure_kind=TestExecutionFailureKind.SELECTION_EVIDENCE,
            )

        outcomes = tuple(result.outcome for result in self.results)
        skipped_count = outcomes.count(TestOutcome.SKIP)
        if skipped_count:
            raise TestExecutionError(
                expectation,
                reason=f"Skipped tests are not allowed: {skipped_count}.",
                summary=self,
                failure_kind=TestExecutionFailureKind.SELECTION_EVIDENCE,
            )

        if expectation is TestExpectation.ALL_PASS:
            unexpected_count = sum(outcome is not TestOutcome.PASS for outcome in outcomes)
            if not unexpected_count:
                return
            reason = f"Expected every test to pass, but {unexpected_count} did not."
        elif expectation is TestExpectation.ALL_FAIL:
            unexpected_count = sum(outcome is not TestOutcome.FAIL for outcome in outcomes)
            if not unexpected_count:
                return
            reason = f"Expected every test to fail, but {unexpected_count} did not."
        elif expectation is TestExpectation.ANY_FAIL:
            if any(outcome is TestOutcome.FAIL for outcome in outcomes):
                return
            reason = "Expected at least one test to fail."
        else:
            raise ValueError(f"Unsupported test expectation: {expectation!r}")

        raise TestExecutionError(expectation, reason=reason, summary=self)


def load_test_run_summary(evidence_dir: Path, test_entries: Iterable[TestEntry]) -> TestRunSummary:
    entries = tuple(test_entries)
    requested = tuple(TestIdentity(entry.codeunitID, function_name) for entry in entries for function_name in sorted(entry.functionName))
    codeunit_ids = tuple(dict.fromkeys(entry.codeunitID for entry in entries))

    discovered: list[TestIdentity] = []
    results: list[TestCaseResult] = []
    for codeunit_id in codeunit_ids:
        discovery_path = evidence_dir / f"discovery-{codeunit_id}.json"
        if discovery_path.exists():
            discovered.extend(_load_discovery(discovery_path, codeunit_id))

        results_path = evidence_dir / f"results-{codeunit_id}.xml"
        if not results_path.exists():
            raise FileNotFoundError(f"Missing JUnit results for codeunit {codeunit_id}: {results_path}")

        root = ET.parse(results_path).getroot()
        for testcase in (node for node in root.iter() if _local_name(node.tag) == "testcase"):
            child_tags = {_local_name(child.tag) for child in testcase}
            function_name = testcase.attrib.get("name")
            if function_name is None:
                raise ValueError(f"JUnit testcase is missing required name attribute for codeunit {codeunit_id}: {results_path}")
            if "error" in child_tags:
                raise ValueError(f"JUnit error evidence for codeunit {codeunit_id}, function {function_name}: {results_path}")
            if "failure" in child_tags:
                outcome = TestOutcome.FAIL
            elif "skipped" in child_tags:
                outcome = TestOutcome.SKIP
            else:
                outcome = TestOutcome.PASS
            results.append(TestCaseResult(TestIdentity(codeunit_id, function_name), outcome))

    return TestRunSummary(requested=requested, discovered=tuple(discovered), results=tuple(results))


def _load_discovery(discovery_path: Path, expected_codeunit_id: int) -> tuple[TestIdentity, ...]:
    discovery: object = json.loads(discovery_path.read_text(encoding="utf-8-sig"))
    if not isinstance(discovery, dict):
        raise ValueError(f"Discovery evidence must be an object: {discovery_path}")  # noqa: TRY004 - Invalid evidence is classified by ValueError.
    discovery_fields = cast(dict[str, object], discovery)

    codeunit_id = discovery_fields.get("codeunitID")
    if type(codeunit_id) is not int or codeunit_id != expected_codeunit_id:
        raise ValueError(f"Discovery evidence codeunitID must equal expected integer {expected_codeunit_id}, got {codeunit_id!r}: {discovery_path}")

    function_names = discovery_fields.get("functionName")
    if not isinstance(function_names, list) or not all(isinstance(function_name, str) for function_name in function_names):
        raise ValueError(f"Discovery evidence functionName must be a list of strings: {discovery_path}")
    validated_function_names = cast(list[str], function_names)

    return tuple(TestIdentity(expected_codeunit_id, function_name) for function_name in validated_function_names)


def _local_name(tag: str) -> str:
    return tag.rpartition("}")[-1]
