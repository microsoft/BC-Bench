import copy
import json
import xml.etree.ElementTree as ET
from enum import StrEnum
from pathlib import Path

from bcbench.dataset import TestEntry
from bcbench.operations.bc_operations import require_test_evidence
from bcbench.operations.test_execution import TestExpectation


class RehearsalFault(StrEnum):
    NONE = "None"
    CORRUPT_BACKUP = "CorruptBackup"
    HASH_MISMATCH = "HashMismatch"
    READINESS_FAILURE = "ReadinessFailure"
    UNEXPECTED_APP = "UnexpectedApp"
    MISSING_JUNIT = "MissingJUnit"
    DUPLICATE_DISCOVERY = "DuplicateDiscovery"
    DUPLICATE_EXECUTION = "DuplicateExecution"
    SERVICE_RESTART_FAILURE = "ServiceRestartFailure"
    CLEANUP_FAILURE = "CleanupFailure"


def inject_test_evidence_fault(fault: RehearsalFault, directory: Path, tests: tuple[TestEntry, ...]) -> None:
    require_test_evidence(directory, tests, TestExpectation.ALL_PASS)
    codeunit_id = tests[0].codeunitID
    discovery = directory / f"discovery-{codeunit_id}.json"
    junit = directory / f"results-{codeunit_id}.xml"
    if fault is RehearsalFault.MISSING_JUNIT:
        junit.unlink()
    elif fault is RehearsalFault.DUPLICATE_DISCOVERY:
        payload = json.loads(discovery.read_text(encoding="utf-8-sig"))
        payload["functionName"].append(payload["functionName"][0])
        discovery.write_text(json.dumps(payload), encoding="utf-8")
    elif fault is RehearsalFault.DUPLICATE_EXECUTION:
        tree = ET.parse(junit)
        case = next(node for node in tree.iter() if node.tag.rpartition("}")[-1] == "testcase")
        tree.getroot().append(copy.deepcopy(case))
        tree.write(junit, encoding="utf-8", xml_declaration=True)
    else:
        raise ValueError(f"Not a test-evidence fault: {fault}")
