import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bcbench.exceptions import AgentError

RUN_MANIFEST_FILE_NAME = "_run-manifest.json"


class ProcessMetrics(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, strict=True)

    cli_version: str | None
    models: list[str]
    usage_complete: bool
    malformed_records: int = Field(ge=0)


class ProcessRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    role: Literal["leaf", "root"]
    ordinal: int = Field(ge=1)
    skill_id: str
    requested_model: str
    observed_models: list[str]
    status: Literal["completed", "failed"]
    started_at: str
    completed_at: str
    duration_seconds: float = Field(ge=0)
    exit_code: int | None
    report_path: str | None
    failure_reason: str | None
    metrics: ProcessMetrics | None


class RunConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    copilot_cli_version: str
    root_model: str
    leaf_model: str
    leaf_execution: Literal["serial", "parallel"]
    max_leaf_concurrency: int = Field(ge=1)
    cli_timeout_minutes: int = Field(ge=0)
    minimum_severity: Literal["Critical", "High", "Medium", "Low"]
    agent_minimum_severity: Literal["Critical", "High", "Medium", "Low"]
    review_source: Literal["pr", "local"]


class ReviewPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    skill_id: Literal["al-code-review"]
    leaf_count: int = Field(ge=1)
    leaf_ids: list[str]

    @model_validator(mode="after")
    def validate_leaf_count(self) -> "ReviewPlan":
        if self.leaf_count != len(self.leaf_ids):
            raise ValueError("leaf_count does not match leaf_ids")
        if len(self.leaf_ids) != len(set(self.leaf_ids)):
            raise ValueError("leaf_ids contains duplicates")
        return self


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    commit: str | None = Field(pattern=r"^[0-9a-f]{40}$")


class EngineRevision(Revision):
    repository: Literal["microsoft/BC-ALAgents"]
    agent_version: str


class BCQualityRevision(Revision):
    source_snapshot: str | None = Field(pattern=r"^[0-9a-f]{64}$")


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    status: Literal["running", "completed", "failed"]
    started_at: str
    completed_at: str | None
    failure_reason: str | None
    engine: EngineRevision
    bcquality: BCQualityRevision
    configuration: RunConfiguration
    plan: ReviewPlan
    processes: list[ProcessRecord]


def load_run_manifest(path: Path) -> RunManifest:
    if not path.exists():
        raise AgentError(f"Engine run manifest artifact not found at {path}.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AgentError(f"Could not read engine run manifest artifact {path}: {exc}") from exc
    try:
        return RunManifest.model_validate(payload)
    except ValidationError as exc:
        raise AgentError(f"Engine run manifest artifact {path} does not satisfy schema version 1: {exc}") from exc


def validate_run_manifest(
    manifest: RunManifest,
    *,
    engine_commit: str,
    cli_version: str,
    root_model: str,
    leaf_model: str,
    leaf_execution: str,
    max_leaf_concurrency: int,
) -> None:
    expected_configuration = {
        "copilot_cli_version": cli_version,
        "root_model": root_model,
        "leaf_model": leaf_model,
        "leaf_execution": leaf_execution,
        "max_leaf_concurrency": max_leaf_concurrency,
        "review_source": "local",
    }
    actual_configuration = manifest.configuration.model_dump()
    mismatches = [f"{name}={actual_configuration[name]!r} (expected {expected!r})" for name, expected in expected_configuration.items() if actual_configuration[name] != expected]
    if manifest.status != "completed":
        mismatches.append(f"status={manifest.status!r} (expected 'completed')")
    if manifest.engine.commit != engine_commit:
        mismatches.append(f"engine.commit={manifest.engine.commit!r} (expected {engine_commit!r})")
    if manifest.bcquality.commit is None:
        mismatches.append("bcquality.commit is missing")
    if manifest.bcquality.source_snapshot is None:
        mismatches.append("bcquality.source_snapshot is missing")

    expected_process_count = manifest.plan.leaf_count + 1
    if len(manifest.processes) != expected_process_count:
        mismatches.append(f"process count={len(manifest.processes)} (expected {expected_process_count})")
    else:
        expected_ordinals = list(range(1, expected_process_count + 1))
        if [process.ordinal for process in manifest.processes] != expected_ordinals:
            mismatches.append("process ordinals do not match the ordered leaf plan")
        leaf_processes = manifest.processes[:-1]
        root_process = manifest.processes[-1]
        if [process.skill_id for process in leaf_processes] != manifest.plan.leaf_ids:
            mismatches.append("leaf process IDs do not match the ordered leaf plan")
        if any(process.role != "leaf" for process in leaf_processes):
            mismatches.append("one or more planned leaf processes have a non-leaf role")
        if root_process.role != "root" or root_process.skill_id != "al-code-review":
            mismatches.append("final process is not the al-code-review root consolidation")

    for process in manifest.processes:
        expected_model = leaf_model if process.role == "leaf" else root_model
        if process.status != "completed" or process.exit_code != 0:
            mismatches.append(f"{process.skill_id} did not complete successfully")
        if process.requested_model != expected_model or process.observed_models != [expected_model]:
            mismatches.append(f"{process.skill_id} model telemetry does not match {expected_model!r}")
        if process.metrics is None:
            mismatches.append(f"{process.skill_id} has no process metrics")
        elif process.metrics.cli_version != cli_version or not process.metrics.usage_complete or process.metrics.malformed_records != 0 or process.metrics.models != [expected_model]:
            mismatches.append(f"{process.skill_id} has incomplete or mismatched process metrics")

    if mismatches:
        raise AgentError("Engine run manifest does not match the pinned experiment: " + "; ".join(mismatches))
