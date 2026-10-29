import argparse
import json
import math
import re
from pathlib import Path

MAX_BYTES = 65536
DIAGNOSTIC_MAX_BYTES = 4096
LEAF_COUNT = 19
MODEL_FIELDS = {
    "failureKind": ("api", "transport", "unknown"),
    "transport": ("http", "websocket", "unknown"),
    "source": ("top_level", "subagent", "mcp_sampling", "unknown"),
    "badRequestKind": ("bodyless", "structured_error", "unknown"),
}
SESSION_TYPES = ("authentication", "authorization", "quota", "rate_limit", "context_limit", "query", "session", "model_call", "unknown")
STAGES = ("process-start", "process-exit", "telemetry", "report-read", "report-parse", "report-validation", "unknown")
CODES = ("start_failed", "process_not_exited", "unknown_failure", "telemetry_invalid", "timeout", "nonzero_exit", "report_missing", "report_invalid_json", "report_invalid", "unknown")
SCALAR_METRICS = (
    "wall_time_seconds",
    "prompt_tokens",
    "cached_tokens",
    "cache_creation_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "total_tokens",
    "api_calls",
    "failed_api_calls",
    "usage_api_calls",
    "ai_credits",
    "premium_requests",
    "malformed_records",
)


def bounded_read(path: Path, root: Path, maximum: int = MAX_BYTES) -> bytes | None:
    for parent in (path, *path.parents):
        if parent.is_symlink() or parent.is_junction():
            raise ValueError("Symbolic links and junctions are not diagnostic inputs")
        if parent == root:
            break
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Diagnostic input outside run directory")
    try:
        with path.open("rb") as stream:
            raw = stream.read(maximum + 1)
    except FileNotFoundError:
        return None
    if len(raw) > maximum:
        raise ValueError("Diagnostic input exceeds byte limit")
    return raw


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate diagnostic key")
        result[key] = value
    return result


def reject_constant(_value: str) -> object:
    raise ValueError("Nonfinite diagnostic number")


def decode_object(raw: bytes) -> dict[str, object]:
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise TypeError("Expected diagnostic object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("Expected string diagnostic key")
        result[key] = item
    return result


def exact_object(value: object, keys: tuple[str, ...]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("Unexpected diagnostic fields")
    return {key: value[key] for key in keys}


def constant(value: object, allowed: tuple[str, ...]) -> str:
    for item in allowed:
        if type(value) is str and value == item:
            return item
    raise ValueError("Invalid diagnostic constant")


def integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid diagnostic integer")
    return value


def boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("Invalid diagnostic boolean")
    return value


def observation(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("Invalid diagnostic observation")
    kind = constant(value.get("type"), ("model.call_failure", "session.error"))
    fields = MODEL_FIELDS if kind == "model.call_failure" else {"errorType": SESSION_TYPES}
    value = exact_object(value, ("type", "status_code", "status_state", *fields))
    state = constant(value["status_state"], ("available", "unavailable", "invalid"))
    status = value["status_code"]
    if state == "available":
        status = integer(status, 400, 599)
    elif status is not None:
        raise ValueError("Unexpected diagnostic HTTP status")
    return {"type": kind, "status_code": status, "status_state": state, **{key: constant(value[key], allowed) for key, allowed in fields.items()}}


def project_diagnostic(value: object, ordinal: int) -> dict[str, object]:
    value = exact_object(value, ("schema_version", "leaf_ordinal", "process", "capture", "cli", "engine"))
    integer(value["schema_version"], 1, 1)
    if integer(value["leaf_ordinal"], 1, LEAF_COUNT) != ordinal:
        raise ValueError("Diagnostic leaf association mismatch")
    process = exact_object(value["process"], ("exit_code", "timeout_observed", "signal"))
    capture = exact_object(value["capture"], ("state", "history_omitted", "records_limited", "leading_record_discarded", "incomplete_record_discarded", "malformed_records", "unsupported_records"))
    cli = exact_object(value["cli"], ("cause", "observations"))
    engine = exact_object(value["engine"], ("stage", "code"))
    events = cli["observations"]
    if not isinstance(events, list) or len(events) > 8:
        raise ValueError("Invalid diagnostic observation count")
    return {
        "schema_version": 1,
        "leaf_ordinal": ordinal,
        "process": {
            "exit_code": None if process["exit_code"] is None else integer(process["exit_code"], -(2**31), 2**31 - 1),
            "timeout_observed": None if process["timeout_observed"] is None else boolean(process["timeout_observed"]),
            "signal": constant(process["signal"], ("unknown",)),
        },
        "capture": {
            "state": constant(capture["state"], ("complete", "truncated", "unavailable", "malformed", "unsupported")),
            **{key: boolean(capture[key]) for key in ("history_omitted", "records_limited", "leading_record_discarded", "incomplete_record_discarded")},
            **{key: integer(capture[key], 0, MAX_BYTES) for key in ("malformed_records", "unsupported_records")},
        },
        "cli": {"cause": constant(cli["cause"], ("unknown",)), "observations": [observation(item) for item in events]},
        "engine": {"stage": constant(engine["stage"], STAGES), "code": constant(engine["code"], CODES)},
    }


def project_metrics(raw: bytes | None) -> dict[str, object] | None:
    if raw is None:
        return None
    value = decode_object(raw)
    selected: dict[str, object] = {}
    for key in SCALAR_METRICS:
        scalar = value.get(key)
        if scalar is not None and not ((type(scalar) is int and 0 <= scalar <= 2**63 - 1) or (type(scalar) is float and math.isfinite(scalar) and scalar >= 0)):
            raise ValueError("Invalid scalar diagnostic metric")
        selected[key] = scalar
    selected["usage_complete"] = boolean(value.get("usage_complete"))
    return selected


def collect(source_dir: Path, output_dir: Path) -> None:
    source_dir = source_dir.absolute()
    if output_dir.resolve().is_relative_to(source_dir.resolve()):
        raise ValueError("Diagnostic output must not overwrite sources")
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "failure-diagnostic.json"
    destination.unlink(missing_ok=True)
    manifest_raw = bounded_read(source_dir / "_run-manifest.json", source_dir)
    diagnostics = []
    selected_metrics = None
    if manifest_raw is not None:
        manifest = decode_object(manifest_raw)
        plan = manifest.get("plan")
        if not isinstance(plan, dict) or type(plan.get("leaf_count")) is not int or plan["leaf_count"] != LEAF_COUNT:
            raise ValueError("Unexpected diagnostic leaf plan")
        ids = plan.get("leaf_ids")
        if (
            not isinstance(ids, list)
            or len(ids) != LEAF_COUNT
            or any(not isinstance(item, str) or re.fullmatch(r"al-[a-z0-9-]{1,60}-review", item) is None for item in ids)
            or len(set(ids)) != LEAF_COUNT
        ):
            raise ValueError("Invalid diagnostic leaf paths")
        for ordinal, identifier in enumerate(ids, 1):
            leaf = source_dir / "leaf-results" / f"{ordinal:02}-{identifier}"
            raw = bounded_read(leaf / "_cli-failure-diagnostic.json", source_dir, DIAGNOSTIC_MAX_BYTES)
            if raw is not None:
                diagnostics.append(project_diagnostic(decode_object(raw), ordinal))
                if len(diagnostics) == 1:
                    selected_metrics = project_metrics(bounded_read(leaf / "_run-metrics.json", source_dir))
    payload = {
        "schema_version": 2,
        "policy": "validated-structured-metadata-and-scalars-only;no-raw-streams",
        "availability": "available" if diagnostics else "unavailable" if manifest_raw is not None else "manifest_unavailable",
        "selection": "first-failed-leaf-in-plan-order",
        "diagnostics_available": len(diagnostics),
        "diagnostics_omitted": max(0, len(diagnostics) - 1),
        "diagnostic": diagnostics[0] if diagnostics else None,
        "metrics": selected_metrics,
    }
    content = (json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    if len(content) > DIAGNOSTIC_MAX_BYTES:
        raise ValueError("Projected diagnostic exceeds byte limit")
    destination.write_bytes(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        collect(args.source_dir, args.output_dir)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise SystemExit("Failure diagnostic collection rejected an unsafe or invalid input") from None
