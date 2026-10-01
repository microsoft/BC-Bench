import json
from pathlib import Path
from typing import Any, Literal

import jsonschema
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
    status: Literal["running", "completed", "partial", "failed"]
    started_at: str
    completed_at: str | None
    failure_reason: str | None
    engine: EngineRevision
    bcquality: BCQualityRevision
    configuration: RunConfiguration
    plan: ReviewPlan
    processes: list[ProcessRecord]

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "RunManifest":
        if self.status == "running":
            if self.completed_at is not None:
                raise ValueError("running manifest must not have completed_at")
            if self.failure_reason is not None:
                raise ValueError("running manifest must not have failure_reason")
        elif self.status == "completed":
            if self.completed_at is None:
                raise ValueError("completed manifest requires completed_at")
            if self.failure_reason is not None:
                raise ValueError("completed manifest must not have failure_reason")
        elif self.status == "partial":
            if self.completed_at is None:
                raise ValueError("partial manifest requires completed_at")
        elif self.status == "failed":
            if self.completed_at is None:
                raise ValueError("failed manifest requires completed_at")
            if not self.failure_reason:
                raise ValueError("failed manifest requires failure_reason")
        return self


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
    cli_timeout_minutes: int,
    minimum_severity: str,
    agent_minimum_severity: str,
) -> None:
    expected_configuration = {
        "copilot_cli_version": cli_version,
        "root_model": root_model,
        "leaf_model": leaf_model,
        "leaf_execution": leaf_execution,
        "max_leaf_concurrency": max_leaf_concurrency,
        "cli_timeout_minutes": cli_timeout_minutes,
        "minimum_severity": minimum_severity,
        "agent_minimum_severity": agent_minimum_severity,
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
        elif (
            not matches_cli_telemetry_version(process.metrics.cli_version, cli_version)
            or not process.metrics.usage_complete
            or process.metrics.malformed_records != 0
            or process.metrics.models != [expected_model]
        ):
            mismatches.append(f"{process.skill_id} has incomplete or mismatched process metrics")

    if mismatches:
        raise AgentError("Engine run manifest does not match the pinned experiment: " + "; ".join(mismatches))


def matches_cli_telemetry_version(observed: str | None, configured: str) -> bool:
    # Engine 2ad4f65's compatibility policy requires a startup probe but permits
    # missing OTel cli_version for 1.0.88. Never fill missing telemetry from a pin.
    return observed == configured or (observed is None and configured == "1.0.88")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentError(f"Required review artifact is missing or unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise AgentError(f"Required review artifact is not a JSON object: {path}")
    return payload


def validate_review_reports(manifest: RunManifest, output_dir: Path) -> None:
    schema = _read_json_object(output_dir / "bcquality" / "schemas" / "findings-report.schema.json")
    reports: dict[str, dict[str, Any]] = {}
    root = output_dir.resolve()
    for process in manifest.processes:
        if not process.report_path:
            raise AgentError(f"{process.skill_id} has no original report path.")
        path = (root / process.report_path).resolve()
        if not path.is_relative_to(root):
            raise AgentError(f"{process.skill_id} report path escapes the output directory.")
        report = _read_json_object(path)
        try:
            jsonschema.validate(report, schema)
        except (jsonschema.ValidationError, jsonschema.SchemaError) as exc:
            raise AgentError(f"{process.skill_id} original report fails the pinned BCQuality schema: {exc.message}") from exc
        if report.get("skill", {}).get("id") != process.skill_id:
            raise AgentError(f"{process.skill_id} original report has the wrong skill identity.")
        if process.role == "leaf" and any(key in report for key in ("sub-results", "skipped-sub-skills")):
            raise AgentError(f"{process.skill_id} original leaf report contains root-only fields.")
        allowed = {"completed"} if process.role == "root" else {"completed", "not-applicable", "no-knowledge"}
        if report.get("outcome") not in allowed:
            raise AgentError(f"{process.skill_id} original report has unusable outcome {report.get('outcome')!r}.")
        if report.get("outcome") != "completed" and report.get("findings"):
            raise AgentError(f"{process.skill_id} inactive leaf report contains findings.")
        reports[process.skill_id] = report

    root_report = reports["al-code-review"]
    nested = root_report.get("sub-results", [])
    if [item.get("skill", {}).get("id") for item in nested] != manifest.plan.leaf_ids:
        raise AgentError("Original root report does not preserve the complete ordered leaf plan.")
    if root_report.get("skipped-sub-skills"):
        raise AgentError("Original root report skips planned leaves.")
    for item in nested:
        skill_id = item["skill"]["id"]
        if item.get("outcome") != reports[skill_id]["outcome"]:
            raise AgentError(f"{skill_id} root sub-result outcome disagrees with its original leaf report.")
        if any(key in item for key in ("sub-results", "skipped-sub-skills")):
            raise AgentError(f"{skill_id} root sub-result contains unexpected nested delegation.")
