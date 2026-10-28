import argparse
import json
import math
import re
from pathlib import Path

MAX_BYTES = 65536
ERROR_PATTERNS = {
    "authentication_missing": r"no authentication information found|not authenticated|authentication required",
    "authentication_failed": r"authentication failed|invalid (?:access )?token|token (?:has )?expired|unauthorized",
    "access_denied": r"forbidden|permission denied|access denied|not authorized",
    "copilot_entitlement": r"(?:copilot|subscription).{0,40}(?:not enabled|not available|not active|does not have access)",
    "model_unavailable": r"model.{0,60}(?:not supported|not available|not found|unavailable)|unsupported model",
    "rate_limited": r"rate limit|too many requests|quota exceeded",
    "version_unsupported": r"(?:version|cli).{0,60}(?:no longer supported|unsupported|outdated|retired)",
    "network_failure": r"econnreset|enotfound|etimedout|fetch failed|connection refused|certificate verify failed",
    "invalid_request": r"bad request|invalid request|invalid argument|unknown option|unrecognized option",
    "service_failure": r"internal server error|service unavailable|bad gateway|gateway timeout",
}
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


def bounded_read(path: Path, root: Path) -> bytes | None:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root.parent):
        raise ValueError("Symbolic links are not diagnostic inputs")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Diagnostic input outside run directory")
    try:
        with path.open("rb") as stream:
            return stream.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return None


def project_output(raw: bytes | None) -> dict[str, object]:
    if raw is None:
        return {"available": False}
    text = raw[:MAX_BYTES].decode("utf-8", errors="replace")
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return {
        "available": True,
        "scanned_bytes": min(len(raw), MAX_BYTES),
        "truncated": len(raw) > MAX_BYTES,
        "signals": sorted(name for name, pattern in ERROR_PATTERNS.items() if re.search(pattern, text, re.IGNORECASE)),
        "http_statuses": sorted({int(match) for match in re.findall(r"\b(?:HTTP(?:/[12](?:\.\d)?)?|status(?: code)?)\s*[:=]?\s*([45]\d\d)\b", text, re.IGNORECASE)}),
        "raw_text_retained": False,
    }


def collect(source_dir: Path, output_dir: Path) -> None:
    leaf = source_dir / "leaf-results" / "01-al-performance-review"
    outputs = {name: project_output(bounded_read(leaf / f"{name}.txt", source_dir)) for name in ("stdout", "stderr")}
    raw_metrics = bounded_read(leaf / "_run-metrics.json", source_dir)
    metrics: dict[str, object] = {}
    if raw_metrics is not None:
        if len(raw_metrics) > MAX_BYTES:
            raise ValueError("Leaf metrics exceed diagnostic limit")
        value = json.loads(raw_metrics.decode("utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("Leaf metrics must be an object")
        for key in SCALAR_METRICS:
            scalar = value.get(key)
            if scalar is None or (type(scalar) in (int, float) and math.isfinite(scalar) and scalar >= 0):
                metrics[key] = scalar
            else:
                raise ValueError("Invalid scalar diagnostic metric")
        if type(value.get("usage_complete")) is not bool:
            raise ValueError("Invalid usage completeness")
        metrics["usage_complete"] = value["usage_complete"]
    payload = {
        "schema_version": 1,
        "leaf": "al-performance-review",
        "policy": "fixed-error-signals-and-nonnegative-scalar-metrics-only;no-raw-output",
        "outputs": outputs,
        "metrics_available": raw_metrics is not None,
        "metrics": metrics,
        "interpretation": "Signals are textual occurrences, not established causes. Unknown messages are intentionally not retained.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "failure-diagnostic.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        collect(args.source_dir, args.output_dir)
    except (OSError, ValueError):
        raise SystemExit("Failure diagnostic collection rejected an unsafe or invalid input") from None
