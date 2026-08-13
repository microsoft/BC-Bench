import json
import re
from pathlib import Path
from typing import Any

from bcbench.agent.copilot.metrics import parse_metrics
from bcbench.logger import get_logger
from bcbench.types import AgentMetrics

logger = get_logger(__name__)

RUN_METRICS_FILE_NAME = "_run-metrics.json"
FILTER_REPORT_FILE_NAME = "_filter-report.json"
TRANSCRIPT_FILE_NAME = "agent-transcript.log"
METRIC_NUMBER_PATTERN = r"[0-9][0-9,]*(?:\.[0-9]+)?[kKmM]?"
AI_CREDITS_PATTERN = re.compile(rf"(?m)^(?:err:\s*)?AI Credits\s+({METRIC_NUMBER_PATTERN})")
PREMIUM_REQUESTS_PATTERN = re.compile(rf"(?:Requests\s+|Total usage est:\s*)({METRIC_NUMBER_PATTERN})\s+Premium", re.IGNORECASE)
TOKENS_PATTERN = re.compile(
    rf"(?m)^(?:err:\s*)?Tokens\s+↑\s*({METRIC_NUMBER_PATTERN})"
    rf"(?:\s+\(({METRIC_NUMBER_PATTERN})\s+cached(?:,\s*{METRIC_NUMBER_PATTERN}\s+written)?\))?"
    rf"\s+•\s+↓\s*({METRIC_NUMBER_PATTERN})"
    rf"(?:\s+\(({METRIC_NUMBER_PATTERN})\s+reasoning\))?"
)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        logger.debug(f"Engine perf file not found: {path}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"Could not read engine perf file {path}: {exc}")
        return None
    if not isinstance(payload, dict):
        logger.warning(f"Engine perf file {path} is not a JSON object; ignoring")
        return None
    return payload


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_compact_number(value: str) -> float:
    normalized = value.replace(",", "").lower()
    multiplier = 1.0
    if normalized.endswith("k"):
        normalized = normalized[:-1]
        multiplier = 1_000.0
    elif normalized.endswith("m"):
        normalized = normalized[:-1]
        multiplier = 1_000_000.0
    return float(normalized) * multiplier


def parse_run_metrics(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if payload is None:
        return {}

    result: dict[str, Any] = {}
    for source_key, target_key, coerce in (
        ("prompt_tokens", "prompt_tokens", _as_int),
        ("completion_tokens", "completion_tokens", _as_int),
        ("total_tokens", "total_tokens", _as_int),
        ("api_calls", "api_calls", _as_int),
        ("estimated_credits", "estimated_credits", _as_float),
        ("wall_time_seconds", "wall_time_seconds", _as_float),
    ):
        value = coerce(payload.get(source_key))
        if value is not None:
            result[target_key] = value

    if "total_tokens" not in result and "prompt_tokens" in result and "completion_tokens" in result:
        result["total_tokens"] = int(result["prompt_tokens"]) + int(result["completion_tokens"])
    return result


def parse_transcript_metrics(path: Path) -> dict[str, int | float]:
    if not path.exists():
        logger.debug(f"Engine transcript not found: {path}")
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        logger.warning(f"Could not read engine transcript {path}: {exc}")
        return {}

    parsed = parse_metrics(lines, session_log_path=path)
    result: dict[str, int | float] = {}
    if parsed:
        if parsed.prompt_tokens is not None:
            result["prompt_tokens"] = parsed.prompt_tokens
        if parsed.completion_tokens is not None:
            result["completion_tokens"] = parsed.completion_tokens
        if parsed.turn_count is not None:
            result["api_calls"] = parsed.turn_count

    transcript = "".join(lines)
    token_matches = list(TOKENS_PATTERN.finditer(transcript))
    if token_matches:
        token_match = token_matches[-1]
        result["prompt_tokens"] = int(_parse_compact_number(token_match.group(1)))
        result["completion_tokens"] = int(_parse_compact_number(token_match.group(3)))

    credit_matches = list(AI_CREDITS_PATTERN.finditer(transcript))
    if not credit_matches:
        credit_matches = list(PREMIUM_REQUESTS_PATTERN.finditer(transcript))
    if credit_matches:
        result["estimated_credits"] = _parse_compact_number(credit_matches[-1].group(1))
    if "prompt_tokens" in result and "completion_tokens" in result:
        result["total_tokens"] = int(result["prompt_tokens"]) + int(result["completion_tokens"])
    return result


def _count_filtered_knowledge(bcquality_root: Path) -> int:
    return sum(1 for path in bcquality_root.rglob("*.md") if path.is_file() and "knowledge" in {part.lower() for part in path.relative_to(bcquality_root).parts[:-1]})


def parse_filter_report(path: Path, bcquality_root: Path) -> dict[str, int]:
    payload = _load_json(path)
    if payload is None:
        return {}
    removed = payload.get("removed")
    if not isinstance(removed, list):
        return {}
    return {
        "knowledge_pruned": sum(1 for item in removed if isinstance(item, dict) and item.get("kind") == "knowledge"),
        "knowledge_used": _count_filtered_knowledge(bcquality_root),
    }


def build_pr_review_metrics(output_dir: Path, bcquality_root: Path, execution_time: float) -> AgentMetrics:
    transcript = parse_transcript_metrics(output_dir / TRANSCRIPT_FILE_NAME)
    run = {**transcript, **parse_run_metrics(output_dir / RUN_METRICS_FILE_NAME)}
    filter_report = output_dir / FILTER_REPORT_FILE_NAME
    if not filter_report.exists():
        filter_report = bcquality_root / FILTER_REPORT_FILE_NAME
    knowledge = parse_filter_report(filter_report, bcquality_root)
    return AgentMetrics(
        execution_time=execution_time,
        prompt_tokens=_as_int(run.get("prompt_tokens")),
        completion_tokens=_as_int(run.get("completion_tokens")),
        total_tokens=_as_int(run.get("total_tokens")),
        api_calls=_as_int(run.get("api_calls")),
        estimated_credits=_as_float(run.get("estimated_credits")),
        knowledge_used=knowledge.get("knowledge_used"),
        knowledge_pruned=knowledge.get("knowledge_pruned"),
    )
