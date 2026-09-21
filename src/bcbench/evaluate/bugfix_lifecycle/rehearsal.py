import copy
import errno
import json
import os
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path, PureWindowsPath
from typing import Protocol

from bcbench.dataset import TestEntry
from bcbench.evaluate.bugfix_lifecycle.checkpoint import CheckpointManager
from bcbench.evaluate.bugfix_lifecycle.evidence import sha256_file
from bcbench.evaluate.bugfix_lifecycle.models import AppInventoryEntry, CheckpointManifest, ProjectPublication
from bcbench.evaluate.bugfix_lifecycle.path_safety import reject_reparse_components
from bcbench.evaluate.bugfix_lifecycle.phases import classify_phase_error
from bcbench.exceptions import CheckpointInfrastructureError, TestExecutionError, TestExecutionFailureKind, TestInfrastructureError
from bcbench.operations.bc_operations import require_test_evidence
from bcbench.operations.project_operations import is_test_project
from bcbench.operations.test_execution import TestExpectation, TestRunSummary
from bcbench.results.bugfix import BugFixPhaseStatus


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


@dataclass(frozen=True)
class RehearsalProbe:
    database_files: tuple[str, ...]
    columns: tuple[str, ...]
    rows: tuple[str, ...]
    discovered: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "RehearsalProbe":
        values = []
        for name in ("database_files", "columns", "rows", "discovered"):
            value = payload.get(name)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise CheckpointInfrastructureError(f"Invalid rehearsal probe {name}")
            values.append(tuple(value))
        require_online_database_files(values[0])
        return cls(*values)


class RehearsalAdapter(Protocol):
    probe_name: str
    fault_applied: bool

    def read_probe(self) -> RehearsalProbe: ...
    def read_inventory(self) -> tuple[AppInventoryEntry, ...]: ...
    def create_probe(self) -> None: ...
    def mutate(self, app: AppInventoryEntry) -> None: ...
    def set_fault(self, fault: RehearsalFault) -> None: ...
    def test_evidence(self, iteration: int) -> tuple[Path, tuple[TestEntry, ...]]: ...


def select_rehearsal_app(
    publication: ProjectPublication,
    baseline: Sequence[AppInventoryEntry],
    entry_projects: Sequence[str],
) -> AppInventoryEntry:
    if not (len(publication.project_paths) == len(publication.apps) == len(publication.package_paths)):
        raise CheckpointInfrastructureError("Baseline publication has no exact project/package provenance")
    for project, package, published in reversed(tuple(zip(publication.project_paths, publication.package_paths, publication.apps, strict=True))):
        if project not in entry_projects or not is_test_project(project):
            continue
        if not package.is_file() or published.content_hash is None or sha256_file(package) != published.content_hash:
            raise CheckpointInfrastructureError("Trusted baseline test package hash mismatch")
        matches = [
            app
            for app in baseline
            if (app.app_id, app.name, app.publisher, app.version) == (published.app_id, published.name, published.publisher, published.version)
            and app.installed
            and app.synchronized
            and (app.package_id is None or published.package_id is None or app.package_id == published.package_id)
            and (app.content_hash is None or app.content_hash == published.content_hash)
        ]
        if len(matches) != 1:
            raise CheckpointInfrastructureError("Published entry test app does not match the exact baseline inventory")
        return matches[0]
    raise CheckpointInfrastructureError("No entry-owned published test app is available for rehearsal")


def require_online_database_files(files: tuple[str, ...]) -> None:
    if not files:
        raise CheckpointInfrastructureError("Rehearsal database_files evidence is missing")
    identities: set[tuple[str, str]] = set()
    for record in files:
        fields = record.split(":", 3)
        if len(fields) != 4 or not fields[0].strip() or not fields[1].isascii() or not fields[1].isdecimal() or int(fields[1]) <= 0 or fields[2] not in {"ROWS", "LOG", "FILESTREAM", "FULLTEXT"}:
            raise CheckpointInfrastructureError("Malformed rehearsal database_files identity")
        path, separator, state = fields[3].rpartition(":")
        if not separator or not PureWindowsPath(path).is_absolute() or not PureWindowsPath(path).name:
            raise CheckpointInfrastructureError("Malformed rehearsal database_files path or state")
        if state != "ONLINE":
            raise CheckpointInfrastructureError("Every rehearsal database_files entry must be ONLINE")
        identity = (fields[0], fields[1])
        if identity in identities:
            raise CheckpointInfrastructureError("Duplicate rehearsal database_files identity")
        identities.add(identity)


def require_same_probe(expected: RehearsalProbe, actual: RehearsalProbe) -> None:
    require_online_database_files(expected.database_files)
    require_online_database_files(actual.database_files)
    for name in ("database_files", "columns", "rows", "discovered"):
        if Counter(getattr(expected, name)) != Counter(getattr(actual, name)):
            raise CheckpointInfrastructureError(f"Rehearsal {name} did not revert exactly")


def write_rehearsal_record(path: Path, payload: object) -> None:
    reject_reparse_components(path, path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


_RESTORE_FAULTS = {
    RehearsalFault.CORRUPT_BACKUP: "Staged checkpoint backup hash mismatch.",
    RehearsalFault.HASH_MISMATCH: "protected checkpoint hash mismatch:",
    RehearsalFault.READINESS_FAILURE: "Business Central readiness evidence was incomplete.",
    RehearsalFault.UNEXPECTED_APP: "Business Central readiness application inventory does not match the checkpoint manifest.",
    RehearsalFault.SERVICE_RESTART_FAILURE: "Business Central service tier was not genuinely restarted.",
}
_EVIDENCE_FAULTS = {RehearsalFault.MISSING_JUNIT, RehearsalFault.DUPLICATE_DISCOVERY, RehearsalFault.DUPLICATE_EXECUTION}


def _require_inventory(expected: Sequence[AppInventoryEntry], actual: Sequence[AppInventoryEntry]) -> None:
    if Counter(expected) != Counter(actual):
        raise CheckpointInfrastructureError("Restored exact app inventory mismatch")


def _require_probe_created(official: RehearsalProbe, expected: RehearsalProbe) -> None:
    require_online_database_files(expected.database_files)
    if not expected.columns or not expected.rows:
        raise CheckpointInfrastructureError("SQL rehearsal probe was not created")
    if Counter(expected.database_files) != Counter(official.database_files) or Counter(expected.discovered) != Counter(official.discovered):
        raise CheckpointInfrastructureError("Probe creation changed database topology or discovery")


def _run_iteration(
    checkpoint: CheckpointManager,
    rehearsal: CheckpointManifest,
    adapter: RehearsalAdapter,
    app: AppInventoryEntry,
    expected: RehearsalProbe,
    iteration: int,
    fault: RehearsalFault,
    record: dict[str, object],
) -> BugFixPhaseStatus:
    adapter.mutate(app)
    changed = adapter.read_probe()
    require_online_database_files(changed.database_files)
    record["mutated_probe"] = asdict(changed)
    if changed.columns == expected.columns or changed.rows == expected.rows:
        raise CheckpointInfrastructureError("Rehearsal did not actually mutate both SQL schema and data")
    actual = adapter.read_inventory()
    record["mutated_inventory"] = [item.to_dict() for item in actual]
    original_others = tuple(item for item in rehearsal.apps if item.app_id != app.app_id)
    changed_app = tuple(item for item in actual if item.app_id == app.app_id)
    if Counter(item for item in actual if item.app_id != app.app_id) != Counter(original_others) or len(changed_app) != 1:
        raise CheckpointInfrastructureError("Inventory mutation changed apps other than the owned test app")
    if changed_app[0].installed or replace(changed_app[0], installed=app.installed, synchronized=app.synchronized) != app:
        raise CheckpointInfrastructureError("Owned test app was not uninstalled without other identity changes")
    adapter.set_fault(fault if fault in _RESTORE_FAULTS and fault is not RehearsalFault.HASH_MISMATCH else RehearsalFault.NONE)
    observed: BaseException | None = None
    try:
        target = replace(rehearsal, sha256="0" * 64) if fault is RehearsalFault.HASH_MISMATCH else rehearsal
        checkpoint.restore(target, rehearsal.apps)
    except CheckpointInfrastructureError as error:
        marker = _RESTORE_FAULTS.get(fault)
        applied = fault is RehearsalFault.HASH_MISMATCH or adapter.fault_applied
        if not applied or marker is None or marker not in str(error) or isinstance(error.__cause__, BaseExceptionGroup):
            raise
        observed = error
    finally:
        adapter.set_fault(RehearsalFault.NONE)
    if fault in _RESTORE_FAULTS:
        if observed is None:
            raise CheckpointInfrastructureError("Injected restore fault was not rejected")
    else:
        restored = adapter.read_probe()
        record["restored_probe"] = asdict(restored)
        require_same_probe(expected, restored)
        _require_inventory(rehearsal.apps, adapter.read_inventory())
        if fault in _EVIDENCE_FAULTS:
            evidence, tests = adapter.test_evidence(iteration)
            proof = inject_test_evidence_fault(fault, evidence, tests)
            try:
                require_test_evidence(evidence, tests, TestExpectation.ALL_PASS)
            except (TestExecutionError, TestInfrastructureError) as error:
                if not proof.matches(error) or classify_phase_error(error) is not BugFixPhaseStatus.INFRASTRUCTURE_ERROR:
                    raise
                observed = error
            if observed is None:
                raise CheckpointInfrastructureError("Injected test-evidence fault was not rejected")
    if observed is None:
        return BugFixPhaseStatus.PASSED
    status = classify_phase_error(observed)
    if status is not BugFixPhaseStatus.INFRASTRUCTURE_ERROR:
        raise CheckpointInfrastructureError("Injected fault was not classified as infrastructure error")
    return status


def run_checkpoint_rehearsal(
    checkpoint: CheckpointManager,
    s0: CheckpointManifest,
    adapter: RehearsalAdapter,
    app: AppInventoryEntry,
    output: Path,
    *,
    iterations: int = 1,
    fault: RehearsalFault = RehearsalFault.NONE,
) -> None:
    if not 1 <= iterations <= 100:
        raise ValueError("Rehearsal iterations must be between 1 and 100")
    if app not in s0.apps:
        raise CheckpointInfrastructureError("Rehearsal app is not in official S0")
    output.mkdir(parents=True, exist_ok=False)
    official = adapter.read_probe()
    require_online_database_files(official.database_files)
    if official.columns or official.rows or not official.database_files or not official.discovered:
        raise CheckpointInfrastructureError("Official S0 must have no rehearsal probe and complete file/discovery evidence")
    if Counter(adapter.read_inventory()) != Counter(s0.apps):
        raise CheckpointInfrastructureError("Official S0 inventory changed before rehearsal")
    created = False
    primary: BaseException | None = None
    try:
        adapter.create_probe()
        created = True
        expected = adapter.read_probe()
        _require_probe_created(official, expected)
        rehearsal = checkpoint.capture(f"rehearsal-{adapter.probe_name[-32:]}", s0.apps)
        write_rehearsal_record(
            output / "checkpoints.json",
            {
                "official_s0": s0.to_dict(),
                "rehearsal_only": rehearsal.to_dict(),
                "probe": adapter.probe_name,
                "expected_probe": asdict(expected),
                "selected_app": app.to_dict(),
            },
        )
        for iteration in range(1, iterations + 1):
            record_path = output / f"iteration-{iteration:04d}.json"
            record: dict[str, object] = {
                "iteration": iteration,
                "fault": fault.value,
                "verified": False,
                "status": "running",
                "official_s0_sha256": s0.sha256,
                "rehearsal_sha256": rehearsal.sha256,
                "container_id": s0.container.container_id,
            }
            write_rehearsal_record(record_path, record)
            try:
                status = _run_iteration(checkpoint, rehearsal, adapter, app, expected, iteration, fault, record)
                record.update(verified=True, status=status.value)
            except BaseException as error:
                status = classify_phase_error(error)
                record.update(status=status.value if status else "unclassified_error", error_type=type(error).__name__)
                raise
            finally:
                write_rehearsal_record(record_path, record)
            if fault is not RehearsalFault.NONE and fault is not RehearsalFault.CLEANUP_FAILURE:
                break
    except BaseException as error:
        primary = error
        raise
    finally:
        if created:
            try:
                adapter.set_fault(RehearsalFault.NONE)
                checkpoint.restore(s0, s0.apps)
                require_same_probe(official, adapter.read_probe())
                _require_inventory(s0.apps, adapter.read_inventory())
                write_rehearsal_record(output / "clean-s0.json", {"verified": True, "checkpoint_sha256": s0.sha256, "probe_absent": True})
            except BaseException as error:
                write_rehearsal_record(output / "clean-s0.json", {"verified": False, "error_type": type(error).__name__})
                # The caller owns the protected root; no cleanup retry can erase this marker.
                write_rehearsal_record(output.parent.parent / "quarantine.json", {"status": "quarantined", "reason": "rehearsal_clean_s0_unverified"})
                if primary is not None:
                    raise BaseExceptionGroup("Rehearsal and clean S0 restoration failed", [primary, error]) from None
                raise


@dataclass(frozen=True)
class InjectedTestEvidenceFault:
    fault: RehearsalFault
    pristine: TestRunSummary
    junit: Path
    files: tuple[tuple[Path, str | None], ...]

    def matches(self, error: TestExecutionError | TestInfrastructureError) -> bool:
        for path, digest in self.files:
            if digest is None:
                if path.exists():
                    return False
            elif not path.is_file() or sha256_file(path) != digest:
                return False
        if error.expectation != TestExpectation.ALL_PASS:
            return False
        if self.fault is RehearsalFault.MISSING_JUNIT:
            cause = error.__cause__
            return (
                isinstance(error, TestInfrastructureError)
                and isinstance(cause, FileNotFoundError)
                and cause.errno == errno.ENOENT
                and cause.filename == str(self.junit)
                and error.reason == f"Invalid test evidence: {cause}"
                and error.summary is None
            )
        if not isinstance(error, TestExecutionError) or error.failure_kind is not TestExecutionFailureKind.SELECTION_EVIDENCE or error.summary is None:
            return False
        summary = error.summary
        discovered = Counter(self.pristine.discovered)
        results = Counter(self.pristine.results)
        if self.fault is RehearsalFault.DUPLICATE_DISCOVERY:
            discovered.update((self.pristine.discovered[0],))
            reason = "Discovery evidence mismatch: missing 0, unexpected 1."
        elif self.fault is RehearsalFault.DUPLICATE_EXECUTION:
            results.update((self.pristine.results[0],))
            reason = "Execution evidence mismatch: missing 0, unexpected 1."
        else:
            return False
        return error.reason == reason and Counter(summary.requested) == Counter(self.pristine.requested) and Counter(summary.discovered) == discovered and Counter(summary.results) == results


def inject_test_evidence_fault(fault: RehearsalFault, directory: Path, tests: tuple[TestEntry, ...]) -> InjectedTestEvidenceFault:
    pristine = require_test_evidence(directory, tests, TestExpectation.ALL_PASS)
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
    paths = tuple(directory / name for codeunit in dict.fromkeys(test.codeunitID for test in tests) for name in (f"discovery-{codeunit}.json", f"results-{codeunit}.xml"))
    return InjectedTestEvidenceFault(fault, pristine, junit, tuple((path, sha256_file(path) if path.exists() else None) for path in paths))
