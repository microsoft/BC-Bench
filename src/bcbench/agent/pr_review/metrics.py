import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bcbench.exceptions import AgentError
from bcbench.types import AgentMetrics

FILTER_REPORT_FILE_NAME = "_filter-report.json"
RUN_METRICS_FILE_NAME = "_run-metrics.json"
_KNOWLEDGE_LAYERS = {"microsoft", "community", "custom"}
_NonNegativeInt = Annotated[int, Field(ge=0)]
_NonNegativeFloat = Annotated[float, Field(ge=0)]


class _FilterRemoval(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    kind: Literal["knowledge", "skill"]


class _FilterReport(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    removed: list[_FilterRemoval]


class _RunMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    metrics_source: Literal["copilot-cli-otel"]
    cli_version: str | None
    wall_time_seconds: _NonNegativeFloat | None
    prompt_tokens: _NonNegativeInt | None
    cached_tokens: _NonNegativeInt | None
    cache_creation_tokens: _NonNegativeInt | None
    completion_tokens: _NonNegativeInt | None
    reasoning_tokens: None
    total_tokens: _NonNegativeInt | None
    api_calls: _NonNegativeInt | None
    failed_api_calls: _NonNegativeInt | None
    usage_api_calls: _NonNegativeInt | None
    ai_credits: _NonNegativeFloat | None
    premium_requests: None
    models: list[str]
    usage_complete: bool
    malformed_records: _NonNegativeInt


def _load_run_metrics(path: Path) -> _RunMetrics:
    if not path.exists():
        raise AgentError(f"Engine run metrics artifact not found at {path}.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AgentError(f"Could not read engine run metrics artifact {path}: {exc}") from exc
    try:
        return _RunMetrics.model_validate(payload)
    except ValidationError as exc:
        raise AgentError(f"Engine run metrics artifact {path} does not satisfy schema version 1: {exc}") from exc


def _load_filter_report(path: Path) -> _FilterReport:
    if not path.exists():
        raise AgentError(f"BCQuality filter report not found at {path}.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AgentError(f"Could not read BCQuality filter report {path}: {exc}") from exc
    try:
        return _FilterReport.model_validate(payload)
    except ValidationError as exc:
        raise AgentError(f"BCQuality filter report {path} has an invalid shape: {exc}") from exc


def _count_available_knowledge(bcquality_root: Path) -> int:
    def is_knowledge_file(path: Path) -> bool:
        parts = path.relative_to(bcquality_root).parts
        return len(parts) >= 3 and parts[0].lower() in _KNOWLEDGE_LAYERS and parts[1].lower() == "knowledge"

    return sum(1 for path in bcquality_root.rglob("*.md") if path.is_file() and is_knowledge_file(path))


def build_pr_review_metrics(output_dir: Path, bcquality_root: Path, execution_time: float) -> AgentMetrics:
    run = _load_run_metrics(output_dir / RUN_METRICS_FILE_NAME)
    report = _load_filter_report(bcquality_root / FILTER_REPORT_FILE_NAME)
    return AgentMetrics(
        execution_time=execution_time,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        cached_tokens=run.cached_tokens,
        cache_creation_tokens=run.cache_creation_tokens,
        total_tokens=run.total_tokens,
        api_calls=run.api_calls,
        failed_api_calls=run.failed_api_calls,
        usage_api_calls=run.usage_api_calls,
        ai_credits=run.ai_credits,
        usage_complete=run.usage_complete,
        malformed_records=run.malformed_records,
        knowledge_files=_count_available_knowledge(bcquality_root),
        knowledge_pruned=sum(1 for item in report.removed if item.kind == "knowledge"),
    )
