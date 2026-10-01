import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bcbench.agent.pr_review.run_manifest import RunManifest
from bcbench.exceptions import AgentError
from bcbench.types import PRReviewMetrics

RUN_METRICS_FILE_NAME = "_run-metrics.json"
_NonNegativeInt = Annotated[int, Field(ge=0)]
_NonNegativeFloat = Annotated[float, Field(ge=0)]


class _RunMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    # "not-applicable" means engine preflight found no .al files, skipped the review, and emitted exact zero usage.
    metrics_source: Literal["copilot-cli-otel", "not-applicable"]
    cli_version: str | None
    wall_time_seconds: _NonNegativeFloat | None
    prompt_tokens: _NonNegativeInt | None
    cached_tokens: _NonNegativeInt | None
    cache_creation_tokens: _NonNegativeInt | None
    completion_tokens: _NonNegativeInt | None
    reasoning_tokens: _NonNegativeInt | None
    total_tokens: _NonNegativeInt | None
    api_calls: _NonNegativeInt | None
    failed_api_calls: _NonNegativeInt | None
    usage_api_calls: _NonNegativeInt | None
    ai_credits: _NonNegativeFloat | None
    premium_requests: _NonNegativeFloat | None
    models: list[str]
    usage_complete: bool
    malformed_records: _NonNegativeInt

    @model_validator(mode="after")
    def validate_not_applicable_shape(self) -> "_RunMetrics":
        if self.metrics_source != "not-applicable":
            return self
        expected = {
            "cli_version": None,
            "wall_time_seconds": 0,
            "prompt_tokens": 0,
            "cached_tokens": 0,
            "cache_creation_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": None,
            "total_tokens": 0,
            "api_calls": 0,
            "failed_api_calls": 0,
            "usage_api_calls": 0,
            "ai_credits": 0.0,
            "premium_requests": None,
            "models": [],
            "usage_complete": True,
            "malformed_records": 0,
        }
        invalid = [name for name, value in expected.items() if getattr(self, name) != value]
        if invalid:
            raise ValueError(f"not-applicable metrics have invalid fields: {', '.join(invalid)}")
        return self


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


def build_pr_review_metrics(output_dir: Path, execution_time: float, manifest: RunManifest | None = None) -> PRReviewMetrics:
    run = _load_run_metrics(output_dir / RUN_METRICS_FILE_NAME)
    if run.metrics_source == "not-applicable":
        raise AgentError("Engine metrics were not applicable. BC-Bench code-review entries must contain AL changes.")
    if manifest:
        expected_models = {manifest.configuration.root_model, manifest.configuration.leaf_model}
        if (
            run.cli_version != manifest.configuration.copilot_cli_version
            or not run.usage_complete
            or run.malformed_records != 0
            or len(run.models) != len(set(run.models))
            or set(run.models) != expected_models
        ):
            raise AgentError("Engine aggregate metrics do not match the validated run manifest.")
    usage_values_available = run.malformed_records == 0
    return PRReviewMetrics(
        execution_time=execution_time,
        prompt_tokens=run.prompt_tokens if usage_values_available else None,
        cached_tokens=run.cached_tokens if usage_values_available else None,
        cache_creation_tokens=run.cache_creation_tokens if usage_values_available else None,
        completion_tokens=run.completion_tokens if usage_values_available else None,
        reasoning_tokens=run.reasoning_tokens if usage_values_available else None,
        total_tokens=run.total_tokens if usage_values_available else None,
        api_calls=run.api_calls if usage_values_available else None,
        failed_api_calls=run.failed_api_calls if usage_values_available else None,
        usage_api_calls=run.usage_api_calls if usage_values_available else None,
        ai_credits=run.ai_credits if usage_values_available else None,
        premium_requests=run.premium_requests if usage_values_available else None,
        models=run.models,
        usage_complete=run.usage_complete,
        malformed_records=run.malformed_records,
        copilot_cli_version=run.cli_version,
        leaf_model=manifest.configuration.leaf_model if manifest else None,
        leaf_execution=manifest.configuration.leaf_execution if manifest else None,
        max_leaf_concurrency=manifest.configuration.max_leaf_concurrency if manifest else None,
        bcquality_commit=manifest.bcquality.commit if manifest else None,
        bcquality_source_snapshot=manifest.bcquality.source_snapshot if manifest else None,
        review_process_count=len(manifest.processes) if manifest else None,
    )
