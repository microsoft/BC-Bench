from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from bcbench.agent.bcal.agent import BCalBackendConfig, _process_output, _resolve_bcal_executable
from bcbench.config import get_config
from bcbench.dataset import BCalScenarioEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.types import AgentMetrics, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()

SCENARIO_MANIFEST = "execution.json"
SCENARIO_RESULT = "evaluation-run.json"
SCENARIO_EXPORT_DIR = "app"
SCENARIO_SYMBOL_DIR = ".bcal-symbols"


class BCalToolUsage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    started: Annotated[int, Field(ge=0)] = 0
    completed: Annotated[int, Field(ge=0)] = 0
    succeeded: Annotated[int, Field(ge=0)] = 0
    failed: Annotated[int, Field(ge=0)] = 0


class BCalFailure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    step_id: str | None = Field(default=None, alias="stepId")


class BCalPlanOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    validation_state: str | None = Field(default=None, alias="validationState")
    deployment_state: str | None = Field(default=None, alias="deploymentState")
    interruption_reason: str | None = Field(default=None, alias="interruptionReason")
    summary_markdown: str | None = Field(default=None, alias="summaryMarkdown")


class BCalPlanFailure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    retryable: bool


class BCalPlanResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    lifecycle: str | None = None
    next_action: str | None = Field(default=None, alias="nextAction")
    available_actions: list[str] = Field(default_factory=list, alias="availableActions")
    outcome: BCalPlanOutcome | None = None
    failure: BCalPlanFailure | None = None


class BCalTokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    input: Annotated[int, Field(ge=0)] = 0
    output: Annotated[int, Field(ge=0)] = 0


class BCalStepResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    id: str
    type: Literal["user", "plan_action"]
    status: str
    assistant_text: str | None = Field(default=None, alias="assistantText")
    compile_succeeded: bool | None = Field(default=None, alias="compileSucceeded")
    plan: BCalPlanResult | None = None
    tokens: BCalTokenUsage = Field(default_factory=BCalTokenUsage)
    duration_ms: Annotated[int, Field(ge=0)] = Field(default=0, alias="durationMs")
    tool_usage: list[BCalToolUsage] = Field(default_factory=list, alias="toolUsage")
    failure: BCalFailure | None = None


class BCalInteractionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    question: str | None = None
    choices: list[str] = Field(default_factory=list)
    allow_freeform: bool | None = Field(default=None, alias="allowFreeform")
    input_type: str | None = Field(default=None, alias="inputType")
    is_required: bool | None = Field(default=None, alias="isRequired")
    recommended_choice_index: int | None = Field(default=None, alias="recommendedChoiceIndex")
    minimum: float | None = None
    maximum: float | None = None


class BCalInteractionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    sequence: Annotated[int, Field(ge=0)]
    rule_id: str | None = Field(default=None, alias="ruleId")
    matched: bool
    used_default: bool = Field(alias="usedDefault")
    request: BCalInteractionRequest
    match: dict[str, object] | None = None
    response: dict[str, object] | None = None
    failure: BCalFailure | None = None


class BCalTotals(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    steps: Annotated[int, Field(ge=0)] = 0
    successful_steps: Annotated[int, Field(ge=0)] = Field(default=0, alias="successfulSteps")
    failed_steps: Annotated[int, Field(ge=0)] = Field(default=0, alias="failedSteps")
    input_tokens: Annotated[int, Field(ge=0)] = Field(default=0, alias="inputTokens")
    output_tokens: Annotated[int, Field(ge=0)] = Field(default=0, alias="outputTokens")
    tool_calls_started: Annotated[int, Field(ge=0)] = Field(default=0, alias="toolCallsStarted")
    tool_calls_completed: Annotated[int, Field(ge=0)] = Field(default=0, alias="toolCallsCompleted")
    duration_ms: Annotated[int, Field(ge=0)] = Field(default=0, alias="durationMs")


class BCalExportResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    attempted: bool
    success: bool
    path: str | None = None
    files_exported: Annotated[int, Field(ge=0)] = Field(default=0, alias="filesExported")
    message: str | None = None


class BCalSessionArchiveResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    attempted: bool
    success: bool
    path: str | None = None
    file_name: str | None = Field(default=None, alias="fileName")
    entries_exported: Annotated[int, Field(ge=0)] = Field(default=0, alias="entriesExported")
    chat_entry_path: str | None = Field(default=None, alias="chatEntryPath")
    message: str | None = None


class BCalScenarioRunResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    completed: bool
    steps: list[BCalStepResult]
    interactions: list[BCalInteractionRecord]
    tool_usage: list[BCalToolUsage] = Field(alias="toolUsage")
    totals: BCalTotals
    export: BCalExportResult
    session_archive: BCalSessionArchiveResult = Field(alias="sessionArchive")
    failure: BCalFailure | None = None


def write_execution_manifest(entry: BCalScenarioEntry, path: Path) -> None:
    manifest = {
        "schemaVersion": "1.0",
        "session": entry.session.model_dump(mode="json", by_alias=True, exclude_none=True),
        "steps": [step.model_dump(mode="json", by_alias=True, exclude_none=True) for step in entry.steps],
        "interactions": [rule.model_dump(mode="json", by_alias=True, exclude_none=True) for rule in entry.interactions],
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def load_scenario_result(path: Path) -> BCalScenarioRunResult:
    if not path.is_file():
        raise AgentError(f"BCal did not write required scenario result: {path}")
    return BCalScenarioRunResult.model_validate_json(path.read_text(encoding="utf-8-sig"))


def _harness_failure(result: BCalScenarioRunResult) -> str | None:
    if not result.export.attempted or not result.export.success:
        return result.export.message or "BCal failed to export the scenario workspace"
    if not result.session_archive.attempted or not result.session_archive.success:
        return result.session_archive.message or "BCal failed to export the sanitized session archive"
    if result.failure and result.failure.step_id is None and result.totals.failed_steps == 0:
        return result.failure.message
    return None


def run_bcal_scenario(
    entry: BCalScenarioEntry,
    repo_path: Path,
    backend_config: BCalBackendConfig,
) -> tuple[AgentMetrics, ExperimentConfiguration]:
    package_cache_path = repo_path / SCENARIO_SYMBOL_DIR / _config.file_patterns.alpackages_dirname
    if not package_cache_path.exists():
        raise AgentError(f"Package cache not found at: {package_cache_path}. Run the setup step first.")

    scenario_path = repo_path / SCENARIO_MANIFEST
    result_path = repo_path / SCENARIO_RESULT
    export_folder = repo_path / SCENARIO_EXPORT_DIR
    write_execution_manifest(entry, scenario_path)
    export_folder.mkdir(parents=True, exist_ok=True)

    cmd_args = [
        _resolve_bcal_executable(),
        "--scenario",
        str(scenario_path),
        "--result",
        str(result_path),
        "--exportfolder",
        str(export_folder),
        f"--packagecachepath={package_cache_path}",
        *backend_config.cli_args(),
    ]
    logger.debug(f"BCal scenario command: {cmd_args}")

    try:
        start = time.monotonic()
        completed = subprocess.run(
            cmd_args,
            timeout=_config.timeout.bcal_execution,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        execution_time = time.monotonic() - start
    except subprocess.TimeoutExpired:
        metrics = AgentMetrics(execution_time=_config.timeout.bcal_execution)
        raise AgentTimeoutError("bcal scenario timed out", metrics=metrics, config=ExperimentConfiguration()) from None

    if completed.returncode != 0:
        logger.warning(
            "BCal scenario exited with status %s; preserving the structured result when available.\n%s",
            completed.returncode,
            "\n".join(filter(None, (_process_output(completed.stdout), _process_output(completed.stderr)))),
        )
        if not result_path.is_file():
            raise AgentError(f"BCal scenario exited with status {completed.returncode} without writing {SCENARIO_RESULT}")

    result = load_scenario_result(result_path)
    if harness_error := _harness_failure(result):
        raise AgentError(f"BCal scenario harness failure: {harness_error}")

    tool_usage: dict[str, int] = {}
    for usage in result.tool_usage:
        tool_usage[usage.name] = tool_usage.get(usage.name, 0) + usage.started
    metrics = AgentMetrics(
        execution_time=execution_time,
        turn_count=result.totals.steps,
        prompt_tokens=result.totals.input_tokens,
        completion_tokens=result.totals.output_tokens,
        total_tokens=result.totals.input_tokens + result.totals.output_tokens,
        tool_usage=tool_usage,
    )
    return metrics, ExperimentConfiguration()


def resolve_session_chat(result: BCalScenarioRunResult, repo_path: Path) -> Path | None:
    archive = result.session_archive
    if not archive.success or not archive.path or not archive.chat_entry_path:
        return None

    archive_path = Path(archive.path)
    if not archive_path.is_absolute():
        archive_path = repo_path / archive_path
    if archive_path.is_dir():
        chat_path = archive_path / archive.chat_entry_path
        return chat_path if chat_path.is_file() else None

    if archive_path.suffix.lower() == ".json" and archive_path.name == archive.chat_entry_path:
        return archive_path if archive_path.is_file() else None

    extracted_dir = repo_path / ".bcal-session-archive"
    if archive_path.suffix.lower() == ".zip" and archive_path.is_file():
        if extracted_dir.exists():
            shutil.rmtree(extracted_dir)
        shutil.unpack_archive(str(archive_path), extracted_dir)
        chat_path = extracted_dir / archive.chat_entry_path
        return chat_path if chat_path.is_file() else None
    return None
