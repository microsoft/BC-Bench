import json
import re
import subprocess
from functools import cache
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.types import AgentMetrics

logger = get_logger(__name__)

RUN_METRICS_FILE_NAME = "_run-metrics.json"
FILTER_REPORT_FILE_NAME = "_filter-report.json"
FINDINGS_FILE_NAME = "al-code-review-findings.json"
_KNOWLEDGE_LAYERS = {"microsoft", "community", "custom"}
_NonNegativeInt = Annotated[int, Field(ge=0)]
_NonNegativeFloat = Annotated[float, Field(ge=0)]


class _FilterRemoval(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    kind: Literal["knowledge", "skill"]


class _FilterReport(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    removed: list[_FilterRemoval]


class _EngineDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True)

    knowledge_used: _NonNegativeInt
    knowledge_suppressed: _NonNegativeInt
    sub_skills_executed: _NonNegativeInt | None
    sub_skills_skipped: _NonNegativeInt


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


def _load_filter_report(path: Path) -> _FilterReport | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AgentError(f"Could not read BCQuality filter report {path}: {exc}") from exc
    try:
        return _FilterReport.model_validate(payload)
    except ValidationError as exc:
        raise AgentError(f"BCQuality filter report {path} has an invalid shape: {exc}") from exc


@cache
def _count_available_knowledge(bcquality_root: Path) -> int:
    def is_knowledge_file(path: Path) -> bool:
        parts = path.relative_to(bcquality_root).parts
        return len(parts) >= 3 and parts[0].lower() in _KNOWLEDGE_LAYERS and parts[1].lower() == "knowledge"

    return sum(1 for path in bcquality_root.rglob("*.md") if path.is_file() and is_knowledge_file(path))


def _normalize_knowledge_reference(path: str) -> str | None:
    parts = path.replace("\\", "/").strip("/").split("/")
    if any(part in {"", ".."} for part in parts) or not parts[-1].lower().endswith(".md"):
        return None
    for index in range(len(parts) - 2):
        if parts[index].lower() in _KNOWLEDGE_LAYERS and parts[index + 1].lower() == "knowledge":
            return "/".join(parts[index:]).lower()
    return None


def _load_engine_diagnostics(path: Path) -> _EngineDiagnostics:
    if not path.exists():
        return _EngineDiagnostics(knowledge_used=0, knowledge_suppressed=0, sub_skills_executed=None, sub_skills_skipped=0)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AgentError(f"Could not read engine findings artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AgentError(f"Engine findings artifact {path} must contain a JSON object.")

    cited: set[str] = set()
    for collection_name in ("findings", "subResults"):
        collection = payload.get(collection_name, [])
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            references = item.get("references", [])
            if not isinstance(references, list):
                continue
            for reference in references:
                if isinstance(reference, dict) and isinstance(reference.get("path"), str):
                    normalized = _normalize_knowledge_reference(reference["path"])
                    if normalized is not None:
                        cited.add(normalized)

    sub_results = payload.get("subResults")
    skipped_sub_skills = payload.get("skippedSubSkills", [])
    suppressed = payload.get("suppressed", [])
    return _EngineDiagnostics(
        knowledge_used=len(cited),
        knowledge_suppressed=len(suppressed) if isinstance(suppressed, list) else 0,
        sub_skills_executed=len(sub_results) if isinstance(sub_results, list) else None,
        sub_skills_skipped=len(skipped_sub_skills) if isinstance(skipped_sub_skills, list) else 0,
    )


def _load_bcquality_identity(engine_root: Path, bcquality_root: Path) -> tuple[str, str, str] | None:
    config_path = engine_root / "agents" / "ALReviewAgent" / "bcquality.config.yaml"
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        bcquality = config["bcquality"]
        repository = bcquality["repo"]
        version = bcquality["version"]
    except (OSError, TypeError, KeyError, yaml.YAMLError) as exc:
        logger.warning(f"BCQuality provenance unavailable from {config_path}: {exc}")
        return None
    if not isinstance(repository, str) or not isinstance(version, str):
        logger.warning(f"BCQuality provenance unavailable: {config_path} must contain string repo and version values.")
        return None
    repository = re.sub(r"\.git$", "", re.sub(r"^(https://github\.com/|git@github\.com:)", "", repository))
    if re.fullmatch(r"[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+", repository) is None:
        logger.warning(f"BCQuality provenance unavailable: invalid repository {repository!r} in {config_path}.")
        return None
    try:
        commit = subprocess.run(
            ["git", "-C", str(bcquality_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(f"BCQuality provenance unavailable from checkout {bcquality_root}: {exc}")
        return None
    if re.fullmatch(r"[0-9a-fA-F]{40}", commit) is None:
        logger.warning(f"BCQuality provenance unavailable: checkout at {bcquality_root} returned invalid commit {commit!r}.")
        return None
    return repository, commit, version


def build_pr_review_metrics(output_dir: Path, bcquality_root: Path, execution_time: float, engine_root: Path | None = None) -> AgentMetrics:
    run = _load_run_metrics(output_dir / RUN_METRICS_FILE_NAME)
    if run.metrics_source == "not-applicable":
        raise AgentError("Engine metrics were not applicable. BC-Bench code-review entries must contain AL changes.")
    report = _load_filter_report(bcquality_root / FILTER_REPORT_FILE_NAME)
    engine = _load_engine_diagnostics(output_dir / FINDINGS_FILE_NAME)
    bcquality_identity = _load_bcquality_identity(engine_root, bcquality_root) if engine_root is not None else None
    usage_values_available = run.malformed_records == 0
    token_values_available = usage_values_available and run.usage_complete
    return AgentMetrics(
        execution_time=execution_time,
        prompt_tokens=run.prompt_tokens if token_values_available else None,
        completion_tokens=run.completion_tokens if token_values_available else None,
        total_tokens=run.total_tokens if token_values_available else None,
        ai_credits=run.ai_credits if usage_values_available else None,
        cached_tokens=run.cached_tokens,
        cache_creation_tokens=run.cache_creation_tokens,
        reasoning_tokens=run.reasoning_tokens,
        api_calls=run.api_calls,
        failed_api_calls=run.failed_api_calls,
        usage_api_calls=run.usage_api_calls,
        premium_requests=run.premium_requests,
        usage_complete=run.usage_complete,
        malformed_records=run.malformed_records,
        knowledge_files=_count_available_knowledge(bcquality_root.resolve()),
        knowledge_pruned=sum(1 for item in report.removed if item.kind == "knowledge") if report is not None else None,
        knowledge_used=engine.knowledge_used,
        knowledge_suppressed=engine.knowledge_suppressed,
        sub_skills_executed=engine.sub_skills_executed,
        sub_skills_skipped=engine.sub_skills_skipped,
        copilot_cli_version=run.cli_version,
        bcquality_repository=bcquality_identity[0] if bcquality_identity else None,
        bcquality_commit=bcquality_identity[1] if bcquality_identity else None,
        bcquality_version=bcquality_identity[2] if bcquality_identity else None,
    )
