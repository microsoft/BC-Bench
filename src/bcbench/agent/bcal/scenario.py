from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, cast, override

from bcbench_core.agent.experiment import ExperimentConfiguration
from bcbench_core.agent.harness import AgentHarness, AgentIdentity, AgentRequest, AgentResult
from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.artifacts import ALPACKAGES_DIRNAME
from bcbench_core.exceptions import AgentError, AgentTimeoutError
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from bcbench.agent.bcal.agent import BCalBackendConfig, _process_output, _resolve_bcal_executable, get_bcal_version
from bcbench.dataset import BCalScenarioEntry
from bcbench.types import HarnessName

logger = logging.getLogger(__name__)

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


class BCalTraceEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    type: str
    name: str | None = None
    sequence: float | None = None
    index: float | None = None


class BCalEvidenceTrace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    events: list[BCalTraceEvent] = Field(default_factory=list)


class BCalEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    trace: BCalEvidenceTrace | None = None


class BCalScenarioRunResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    schema_version: Literal["1.0", "1.1"] = Field(alias="schemaVersion")
    completed: bool
    steps: list[BCalStepResult]
    interactions: list[BCalInteractionRecord] = Field(default_factory=list)
    tool_usage: list[BCalToolUsage] = Field(default_factory=list, alias="toolUsage")
    totals: BCalTotals
    export: BCalExportResult
    evidence: BCalEvidence | None = None
    failure: BCalFailure | None = None


def write_execution_manifest(entry: BCalScenarioEntry, path: Path) -> None:
    manifest = {
        "schemaVersion": "1.0",
        "session": entry.session.model_dump(mode="json", by_alias=True, exclude_none=True),
        "steps": [step.model_dump(mode="json", by_alias=True, exclude_none=True) for step in entry.steps],
        "interactions": [rule.model_dump(mode="json", by_alias=True, exclude_none=True) for rule in entry.interactions],
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def load_scenario_result(path: Path) -> tuple[BCalScenarioRunResult, dict[str, JsonValue]]:
    if not path.is_file():
        raise AgentError(f"BCal did not write required scenario result: {path}")
    try:
        payload = cast(dict[str, JsonValue], json.loads(path.read_bytes()))
        return BCalScenarioRunResult.model_validate(payload), payload
    except (OSError, ValueError) as exc:
        raise AgentError(f"Could not read BCal scenario result {path}: {exc}") from exc


def _read_transcript_after_failure(path: Path) -> dict[str, JsonValue] | None:
    try:
        return load_scenario_result(path)[1]
    except AgentError:
        logger.warning("No usable BCal scenario transcript after failure", exc_info=True)
        return None


def _harness_failure(result: BCalScenarioRunResult) -> str | None:
    if not result.export.attempted or not result.export.success:
        return result.export.message or "BCal failed to export the scenario workspace"
    if result.failure and result.failure.step_id is None and result.totals.failed_steps == 0:
        return result.failure.message
    return None


@dataclass(frozen=True)
class BCalScenarioHarness(AgentHarness[BCalScenarioEntry, HarnessName]):
    backend_config: BCalBackendConfig
    timeout: int = 25 * 60

    @override
    def identity(self) -> AgentIdentity[HarnessName]:
        return AgentIdentity[HarnessName](
            harness=HarnessName.BCAL,
            version=get_bcal_version(),
            model=self.backend_config.model or "external-command",
        )

    @override
    def run(self, request: AgentRequest[BCalScenarioEntry], /) -> AgentResult:
        entry, repo_path = request.task, request.work_dir
        timeout = self.timeout if request.timeout is None else request.timeout
        package_cache_path = repo_path / SCENARIO_SYMBOL_DIR / ALPACKAGES_DIRNAME
        if not package_cache_path.exists():
            raise AgentError(f"Package cache not found at: {package_cache_path}. Run the setup step first.")

        scenario_path = repo_path / SCENARIO_MANIFEST
        result_path = repo_path / SCENARIO_RESULT
        export_folder = repo_path / SCENARIO_EXPORT_DIR
        write_execution_manifest(entry, scenario_path)
        export_folder.mkdir(parents=True, exist_ok=True)
        result_path.unlink(missing_ok=True)

        cmd_args = [
            _resolve_bcal_executable(),
            f"--scenario={scenario_path}",
            f"--result={result_path}",
            f"--exportfolder={export_folder}",
            f"--packagecachepath={package_cache_path}",
            "--include-evidence",
            *self.backend_config.cli_args(),
        ]
        logger.debug("BCal scenario command: %s", cmd_args)

        try:
            start = time.monotonic()
            completed = subprocess.run(
                cmd_args,
                timeout=timeout,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            execution_time = time.monotonic() - start
        except subprocess.TimeoutExpired:
            raise AgentTimeoutError(
                "bcal scenario timed out",
                metrics=AgentMetrics(execution_time=timeout),
                config=ExperimentConfiguration(),
                transcript=_read_transcript_after_failure(result_path),
            ) from None

        if completed.returncode != 0:
            logger.warning(
                "BCal scenario exited with status %s; preserving structured evidence when available.\n%s",
                completed.returncode,
                "\n".join(filter(None, (_process_output(completed.stdout), _process_output(completed.stderr)))),
            )
            if not result_path.is_file():
                raise AgentError(f"BCal scenario exited with status {completed.returncode} without writing {SCENARIO_RESULT}")

        result, transcript = load_scenario_result(result_path)
        if harness_error := _harness_failure(result):
            raise AgentError(f"BCal scenario harness failure: {harness_error}", transcript=transcript)

        return AgentResult(
            metrics=AgentMetrics(execution_time=execution_time),
            experiment=ExperimentConfiguration(),
            transcript=transcript,
        )
