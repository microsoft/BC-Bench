import argparse
import hashlib
import json
import math
from collections.abc import Mapping
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
    return selected


def write_json(path: Path, value: object) -> str:
    content = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


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
    for name in (*FILES, "evidence-status.json"):
        (output_dir / name).unlink(missing_ok=True)
    file_statuses: dict[str, dict[str, str]] = {}
    status: dict[str, object] = {
        "schema_version": 1,
        "entry_id": entry_id,
        "evaluation_outcome": evaluation_outcome,
        "workflow_sha": workflow_sha,
        "workflow_run_id": run_id,
        "workflow_run_attempt": run_attempt,
        "projection": "Allowlisted runtime identity, process status and numerical usage only; failure text, paths, source snapshots, prompts and environment are omitted.",
        "files": file_statuses,
    }
    problems = []
    for name, project in zip(FILES, (manifest, metrics), strict=True):
        source = source_dir / name
        if evaluation_outcome == "skipped":
            file_statuses[name] = {"status": "not_collected_step_skipped"}
            continue
        if source.is_symlink():
            file_statuses[name] = {"status": "rejected_symbolic_link"}
            problems.append(f"{name}: symbolic link rejected")
            continue
        try:
            raw = source.read_bytes()
            projected = project(json.loads(raw.decode("utf-8-sig")))
        except FileNotFoundError:
            file_statuses[name] = {"status": "missing"}
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
        if name == "_run-manifest.json" and evaluation_outcome == "success" and projected["status"] not in {"completed", "partial"}:
            problems.append("Manifest is not a completed or partial review")
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
