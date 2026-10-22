import argparse
import hashlib
import json
import math
import re
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from pathlib import Path

NULLABLE_NUMBER = (int, float, type(None))
NULLABLE_INT = (int, type(None))
NULLABLE_TEXT = (str, type(None))
METRIC_FIELDS = {
    "schema_version": int,
    "metrics_source": str,
    "cli_version": NULLABLE_TEXT,
    "wall_time_seconds": NULLABLE_NUMBER,
    "prompt_tokens": NULLABLE_INT,
    "cached_tokens": NULLABLE_INT,
    "cache_creation_tokens": NULLABLE_INT,
    "completion_tokens": NULLABLE_INT,
    "reasoning_tokens": NULLABLE_INT,
    "total_tokens": NULLABLE_INT,
    "api_calls": NULLABLE_INT,
    "failed_api_calls": NULLABLE_INT,
    "usage_api_calls": NULLABLE_INT,
    "ai_credits": NULLABLE_NUMBER,
    "premium_requests": NULLABLE_NUMBER,
    "usage_complete": bool,
    "malformed_records": int,
}
CONFIGURATION_FIELDS = {
    "copilot_cli_version": str,
    "root_model": str,
    "leaf_model": str,
    "leaf_execution": str,
    "max_leaf_concurrency": int,
    "cli_timeout_minutes": (int, float),
    "minimum_severity": str,
    "agent_minimum_severity": str,
    "review_source": str,
}
PROCESS_FIELDS = {
    "role": str,
    "ordinal": int,
    "skill_id": str,
    "requested_model": str,
    "status": str,
    "started_at": str,
    "completed_at": str,
    "duration_seconds": (int, float),
    "exit_code": NULLABLE_INT,
}
FILES = ("_run-manifest.json", "_run-metrics.json")
TRACE_FILE = "_review-trace.json"
TRACE_MAX_BYTES = 4 * 1024 * 1024
FINAL_INDEX_BASIS = "_review-report.json#/findings;zero-based;before-engine-filtering"
TRACE_STAGES = {"process-start", "process-exit", "telemetry", "report-read", "report-parse", "report-validation", "report-outcome", "consolidation", "unknown"}
TRACE_CODES = {
    "start_failed",
    "timeout",
    "nonzero_exit",
    "process_not_exited",
    "telemetry_invalid",
    "report_missing",
    "report_invalid_json",
    "report_invalid",
    "report_failed",
    "report_partial",
    "coverage_partial",
    "all_leaves_failed",
    "unknown_failure",
    None,
}


def enum_value(value: object, allowed: AbstractSet[str | None]) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError("Invalid enum")
    if value not in allowed:
        raise ValueError("Invalid enum")
    return value


def integer_value(value: object, minimum: int = 0, maximum: int = 2147483647) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid integer")
    return value


def nullable_integer(value: object, minimum: int = 1) -> int | None:
    return None if value is None else integer_value(value, minimum)


def pattern_value(value: object, pattern: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or re.fullmatch(pattern, value) is None:
        raise ValueError("Invalid bounded identifier")
    return value


def bounded_array(value: object, maximum: int) -> list[object]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("Invalid bounded array")
    result: list[object] = []
    result.extend(value)
    return result


def article_refs(value: object) -> list[str] | None:
    if value is None:
        return None
    refs = [pattern_value(item, r"(microsoft|community|custom)/knowledge/[a-z0-9-]+/[a-z0-9-]+\.md", 200) for item in bounded_array(value, 8)]
    if len(set(refs)) != len(refs):
        raise ValueError("Duplicate article references")
    return refs


def trace_finding(value: dict[str, object]) -> dict[str, object]:
    location = object_value(value["location"])
    file = location["file"]
    if file is not None:
        file = pattern_value(file, r"(?!/)(?!.*(?:^|/)\.{1,2}(?:/|$))(?!.*//)[A-Za-z0-9_. /()\-]+", 240)
    line = nullable_integer(location["line"])
    end_line = nullable_integer(location["end_line"])
    if line is not None and end_line is not None and end_line < line:
        raise ValueError("Reversed location")
    return {
        "article_refs": article_refs(value["article_refs"]),
        "location": {"file": file, "line": line, "end_line": end_line},
        "severity": enum_value(value["severity"], {"blocker", "major", "minor", "info", "Critical", "High", "Medium", "Low", None}),
    }


def review_trace(value: object) -> dict[str, object]:
    value = object_value(value)
    selected = select_fields(value, {"schema_version": int, "truncated": bool})
    if selected["schema_version"] != 1 or value["final_index_basis"] != FINAL_INDEX_BASIS:
        raise ValueError("Unsupported trace identity")
    selected["final_index_basis"] = FINAL_INDEX_BASIS
    selected["status"] = enum_value(value["status"], {"running", "completed", "partial", "failed"})
    selected["disposition_status"] = enum_value(value["disposition_status"], {"not_requested", "missing", "invalid", "provided"})
    candidates = []
    candidate_ids = set()
    for raw in bounded_array(value["candidates"], 1000):
        candidate = object_value(raw)
        ordinal = integer_value(candidate["leaf_ordinal"], 1)
        index = integer_value(candidate["finding_index"])
        identifier = pattern_value(candidate["candidate_id"], r"l[0-9]+-f[0-9]+", 40)
        if identifier != f"l{ordinal}-f{index}" or identifier in candidate_ids:
            raise ValueError("Invalid candidate identity")
        candidate_ids.add(identifier)
        leaf = candidate["leaf_id"]
        sha = candidate["report_sha256"]
        normalizations = [enum_value(item, {"finding-id", "location-range"}) for item in bounded_array(candidate["normalizations"], 2)]
        if len(set(normalizations)) != len(normalizations):
            raise ValueError("Duplicate normalizations")
        body = candidate["body"]
        body_status = enum_value(candidate["body_status"], {"retained", "truncated", "redacted", "omitted"})
        if body is not None and (not isinstance(body, str) or len(body) > 1024 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", body)):
            raise ValueError("Invalid bounded finding body")
        if (body is None) != (body_status == "omitted"):
            raise ValueError("Inconsistent finding body status")
        candidates.append(
            {
                "candidate_id": identifier,
                "leaf_id": None if leaf is None else pattern_value(leaf, r"[a-z0-9-]+", 80),
                "leaf_ordinal": ordinal,
                "finding_index": index,
                "report_sha256": None if sha is None else pattern_value(sha, r"[a-f0-9]{64}", 64),
                "admission": enum_value(candidate["admission"], {"accepted", "rejected", "unknown"}),
                **trace_finding(candidate),
                "normalizations": normalizations,
                "body": body,
                "body_status": body_status,
            }
        )
    final_findings = []
    final_indices = set()
    for raw in bounded_array(value["final_findings"], 1000):
        finding = object_value(raw)
        index = integer_value(finding["final_index"])
        if index in final_indices:
            raise ValueError("Duplicate final index")
        final_indices.add(index)
        final_findings.append({"final_index": index, **trace_finding(finding)})
    dispositions = []
    disposition_ids = set()
    for raw in bounded_array(value["root_dispositions"], 1000):
        disposition = object_value(raw)
        identifier = pattern_value(disposition["candidate_id"], r"l[0-9]+-f[0-9]+", 40)
        if identifier not in candidate_ids or identifier in disposition_ids:
            raise ValueError("Invalid disposition candidate")
        disposition_ids.add(identifier)
        indices = disposition["final_indices"]
        if indices is not None:
            indices = [integer_value(item, maximum=999) for item in bounded_array(indices, 8)]
            if len(set(indices)) != len(indices) or not set(indices) <= final_indices:
                raise ValueError("Invalid disposition target")
        dispositions.append(
            {
                "candidate_id": identifier,
                "disposition": enum_value(disposition["disposition"], {"kept", "merged", "downgraded", "removed", "unknown"}),
                "final_indices": indices,
                "basis": enum_value(disposition["basis"], {"model_declared", "unknown"}),
                "reason_code": enum_value(disposition["reason_code"], {"duplicate", "severity_reassessment", "unsupported", "out_of_scope", "not_actionable", None}),
                "article_refs": article_refs(disposition["article_refs"]),
            }
        )
    diagnostics = []
    for raw in bounded_array(value["diagnostics"], 128):
        diagnostic = object_value(raw)
        diagnostics.append(
            {
                "role": enum_value(diagnostic["role"], {"leaf", "root", "run"}),
                "ordinal": nullable_integer(diagnostic["ordinal"]),
                "stage": enum_value(diagnostic["stage"], TRACE_STAGES),
                "code": enum_value(diagnostic["code"], TRACE_CODES),
                "process_status": enum_value(diagnostic["process_status"], {"completed", "failed", "unknown"}),
                "report_outcome": enum_value(diagnostic["report_outcome"], {"completed", "not-applicable", "no-knowledge", "partial", "failed", None}),
                "exit_code": nullable_integer(diagnostic["exit_code"], -2147483648),
            }
        )
    return {**selected, "candidates": candidates, "final_findings": final_findings, "root_dispositions": dispositions, "diagnostics": diagnostics}


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("Expected an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("Expected string keys")
        result[key] = item
    return result


def select_fields(value: object, fields: Mapping[str, type | tuple[type, ...]]) -> dict[str, object]:
    value = object_value(value)
    selected = {}
    for key, types in fields.items():
        item = value[key]
        allowed = types if isinstance(types, tuple) else (types,)
        if type(item) not in allowed or (isinstance(item, float) and not math.isfinite(item)):
            raise ValueError("Invalid field type")
        selected[key] = item
    return selected


def text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        raise TypeError("Expected a string array")
    result = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError("Expected string items")
        result.append(item)
    return result


def metrics(value: object) -> dict[str, object]:
    value = object_value(value)
    if value.get("schema_version") != 1:
        raise ValueError("Unsupported metrics schema")
    return {**select_fields(value, METRIC_FIELDS), "models": text_list(value["models"])}


def manifest(value: object) -> dict[str, object]:
    value = object_value(value)
    if value.get("schema_version") != 1:
        raise ValueError("Unsupported manifest schema")
    selected = select_fields(value, {"schema_version": int, "status": str, "started_at": str, "completed_at": NULLABLE_TEXT})
    selected["engine"] = select_fields(value["engine"], {"repository": str, "commit": NULLABLE_TEXT, "agent_version": str})
    selected["bcquality"] = select_fields(value["bcquality"], {"commit": NULLABLE_TEXT})
    selected["configuration"] = select_fields(value["configuration"], CONFIGURATION_FIELDS)
    plan = object_value(value["plan"])
    selected["plan"] = {**select_fields(plan, {"skill_id": str, "leaf_count": int}), "leaf_ids": text_list(plan["leaf_ids"])}
    processes = value["processes"]
    if not isinstance(processes, list):
        raise TypeError("Expected process records")
    selected_processes = []
    for raw_process in processes:
        process = object_value(raw_process)
        selected_processes.append(
            {
                **select_fields(process, PROCESS_FIELDS),
                "observed_models": text_list(process["observed_models"]),
                "failure_reason_present": bool(process.get("failure_reason")),
            }
        )
    selected["processes"] = selected_processes
    selected["failure_reason_present"] = bool(value.get("failure_reason"))
    if "trace_schema_version" in value:
        selected["trace_schema_version"] = integer_value(value["trace_schema_version"], 1, 1)
    return selected


def write_json(path: Path, value: object) -> str:
    content = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def read_trace(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(TRACE_MAX_BYTES + 1)
    if len(raw) > TRACE_MAX_BYTES:
        raise ValueError("Trace exceeds byte bound")
    return raw


def collect(
    source_dir: Path,
    output_dir: Path,
    entry_id: str,
    evaluation_outcome: str,
    workflow_sha: str,
    run_id: str,
    run_attempt: str,
) -> int:
    if output_dir.resolve() == source_dir.resolve():
        raise ValueError("Evidence output must not overwrite its sources")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in (*FILES, TRACE_FILE, "evidence-status.json"):
        (output_dir / name).unlink(missing_ok=True)
    file_statuses: dict[str, dict[str, str]] = {}
    status: dict[str, object] = {
        "schema_version": 1,
        "entry_id": entry_id,
        "evaluation_outcome": evaluation_outcome,
        "workflow_sha": workflow_sha,
        "workflow_run_id": run_id,
        "workflow_run_attempt": run_attempt,
        "projection": "Allowlisted runtime identity, process status, numerical usage, bounded review lineage and engine-sanitized candidate prose; raw failure/root-reason text, report paths, source snapshots, prompts, transcripts and environment are omitted.",
        "files": file_statuses,
    }
    problems = []
    trace_required = False
    for name, project in zip((*FILES, TRACE_FILE), (manifest, metrics, review_trace), strict=True):
        source = source_dir / name
        if evaluation_outcome == "skipped":
            file_statuses[name] = {"status": "not_collected_step_skipped"}
            continue
        if source.is_symlink():
            file_statuses[name] = {"status": "rejected_symbolic_link"}
            problems.append(f"{name}: symbolic link rejected")
            continue
        try:
            raw = read_trace(source) if name == TRACE_FILE else source.read_bytes()
            projected = project(json.loads(raw.decode("utf-8-sig")))
        except FileNotFoundError:
            legacy = name == TRACE_FILE and not trace_required and file_statuses[FILES[0]]["status"] == "preserved"
            file_statuses[name] = {"status": "not_available_legacy" if legacy else "missing"}
            if not legacy:
                problems.append(f"{name}: missing")
            continue
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            file_statuses[name] = {"status": "unreadable_or_invalid"}
            problems.append(f"{name}: unreadable or invalid")
            continue
        file_statuses[name] = {
            "status": "preserved",
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "artifact_sha256": write_json(output_dir / name, projected),
        }
        if name == "_run-manifest.json":
            trace_required = projected.get("trace_schema_version") == 1
        if name in {"_run-manifest.json", TRACE_FILE} and evaluation_outcome == "success" and projected["status"] not in {"completed", "partial"}:
            problems.append(f"{name}: not a completed or partial review")
    status["problems"] = problems
    write_json(output_dir / "evidence-status.json", status)
    if problems:
        # Do not echo exception text or source values; they can contain failed command arguments.
        level = "error" if evaluation_outcome == "success" else "warning"
        print(f"::{level}::Runtime evidence incomplete: {'; '.join(problems)}")
    return 1 if problems and evaluation_outcome == "success" else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--entry-id", required=True)
    parser.add_argument("--evaluation-outcome", choices=("success", "failure", "cancelled", "skipped"), required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    args = parser.parse_args()
    return collect(**vars(args))


if __name__ == "__main__":
    raise SystemExit(main())
