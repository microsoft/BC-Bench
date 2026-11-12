from __future__ import annotations

import hashlib
import json
import logging
import shutil
import struct
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
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from bcbench.agent.bcal.agent import BCalBackendConfig, _bcal_process_environment, _process_output, _require_completed, _resolve_bcal_executable, _result_metrics, _run_bcal_process, get_bcal_version
from bcbench.dataset import BCalScenarioEntry
from bcbench.types import BCalAgentRuntime, HarnessName

logger = logging.getLogger(__name__)

SCENARIO_MANIFEST = "execution.json"
SCENARIO_RESULT = "evaluation-run.json"
SCENARIO_EXPORT_DIR = "app"
SCENARIO_SYMBOL_DIR = ".bcal-symbols"
SCENARIO_CONTRACT_VERSION = "1.1"
WORKSPACE_SEED_CONTRACT_VERSION = "1.0"


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

    @field_validator("choices", mode="before")
    @classmethod
    def normalize_absent_choices(cls, value: object) -> object:
        return [] if value is None else value


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


class BCalWorkspaceSeedFileReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path_sha256: str = Field(alias="pathSha256")
    content_sha256: str = Field(alias="contentSha256")
    bytes: Annotated[int, Field(ge=0)]


class BCalWorkspaceSeedEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["1.0"] = Field(alias="contractVersion")
    file_count: Annotated[int, Field(ge=0)] = Field(alias="fileCount")
    aggregate_bytes: Annotated[int, Field(ge=0)] = Field(alias="aggregateBytes")
    aggregate_sha256: str = Field(alias="aggregateSha256")
    files: list[BCalWorkspaceSeedFileReceipt]


class BCalScenarioRunResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0", "1.1"] = Field(alias="schemaVersion")
    execution_identity: dict[str, object] | None = Field(default=None, alias="executionIdentity")
    runtime_identity: dict[str, object] | None = Field(default=None, alias="runtimeIdentity")
    agent_runtime_evidence: list[dict[str, object]] = Field(default_factory=list, alias="agentRuntimeEvidence")
    evidence: dict[str, object] | None = None
    outcome: dict[str, object] | None = None
    workspace_seed: BCalWorkspaceSeedEvidence | None = Field(default=None, alias="workspaceSeed")
    completed: bool
    steps: list[BCalStepResult]
    interactions: list[BCalInteractionRecord]
    tool_usage: list[BCalToolUsage] = Field(alias="toolUsage")
    totals: BCalTotals
    export: BCalExportResult
    session_archive: BCalSessionArchiveResult = Field(alias="sessionArchive")
    failure: BCalFailure | None = None

    @property
    def prompt_evidence(self) -> dict[str, object] | None:
        value = self.evidence.get("promptEvidence") if self.evidence else None
        return cast(dict[str, object], value) if isinstance(value, dict) else None

    @property
    def canonical_trace(self) -> dict[str, object] | None:
        value = self.evidence.get("trace") if self.evidence else None
        return cast(dict[str, object], value) if isinstance(value, dict) else None


def workspace_seed_evidence(seed_folder: Path) -> BCalWorkspaceSeedEvidence:
    aggregate = hashlib.sha256()
    receipts: list[BCalWorkspaceSeedFileReceipt] = []
    aggregate_bytes = 0
    paths = sorted(
        (path for path in seed_folder.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(seed_folder).as_posix().encode("utf-16-be"),
    )
    for path in paths:
        relative_path = path.relative_to(seed_folder).as_posix()
        path_bytes = relative_path.encode()
        content = path.read_bytes()
        for value in (path_bytes, content):
            aggregate.update(struct.pack(">I", len(value)))
            aggregate.update(value)
        aggregate_bytes += len(content)
        receipts.append(
            BCalWorkspaceSeedFileReceipt(
                pathSha256=hashlib.sha256(path_bytes).hexdigest(),
                contentSha256=hashlib.sha256(content).hexdigest(),
                bytes=len(content),
            )
        )
    return BCalWorkspaceSeedEvidence(
        contractVersion=WORKSPACE_SEED_CONTRACT_VERSION,
        fileCount=len(receipts),
        aggregateBytes=aggregate_bytes,
        aggregateSha256=aggregate.hexdigest(),
        files=receipts,
    )


def write_execution_manifest(entry: BCalScenarioEntry, path: Path) -> None:
    manifest = {
        "schemaVersion": SCENARIO_CONTRACT_VERSION,
        "session": entry.session.model_dump(mode="json", by_alias=True, exclude_none=True),
        "workspaceSeed": {
            "contractVersion": WORKSPACE_SEED_CONTRACT_VERSION,
            "folder": f"./{SCENARIO_EXPORT_DIR}",
        },
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


@dataclass(frozen=True)
class BCalScenarioHarness(AgentHarness[BCalScenarioEntry, HarnessName]):
    backend_config: BCalBackendConfig
    timeout: int = 25 * 60

    @override
    def identity(self) -> AgentIdentity[HarnessName]:
        self.backend_config.cli_args()
        self.backend_config.validate_deadline(self.timeout)
        return AgentIdentity[HarnessName](
            harness=HarnessName.BCAL,
            version=get_bcal_version(),
            model=(self.backend_config.sdk_model if self.backend_config.agent_runtime == BCalAgentRuntime.COPILOT_SDK else self.backend_config.model) or "external-command",
        )

    @override
    def run(self, request: AgentRequest[BCalScenarioEntry], /) -> AgentResult:
        entry, repo_path = request.task, request.work_dir
        timeout = self.timeout if request.timeout is None else request.timeout
        self.backend_config.validate_deadline(timeout)
        package_cache_path = repo_path / SCENARIO_SYMBOL_DIR / ALPACKAGES_DIRNAME
        if not package_cache_path.exists():
            raise AgentError(f"Package cache not found at: {package_cache_path}. Run the setup step first.")

        scenario_path = repo_path / SCENARIO_MANIFEST
        result_path = repo_path / SCENARIO_RESULT
        export_folder = repo_path / SCENARIO_EXPORT_DIR
        write_execution_manifest(entry, scenario_path)
        export_folder.mkdir(parents=True, exist_ok=True)
        result_path.unlink(missing_ok=True)
        expected_seed = workspace_seed_evidence(export_folder)

        cmd_args = [
            _resolve_bcal_executable(),
            "--scenario",
            str(scenario_path),
            "--result",
            str(result_path),
            "--exportfolder",
            str(export_folder),
            f"--packagecachepath={package_cache_path}",
            "--include-evidence",
            *self.backend_config.cli_args(),
        ]
        logger.debug("BCal scenario command: %s", cmd_args)

        try:
            with _bcal_process_environment() as environment:
                start = time.monotonic()
                if self.backend_config.agent_runtime == BCalAgentRuntime.COPILOT_SDK:
                    try:
                        completed = _run_bcal_process(cmd_args, timeout=timeout, env=environment)
                    except subprocess.CalledProcessError as error:
                        completed = subprocess.CompletedProcess(cmd_args, error.returncode, stdout=error.output, stderr=error.stderr)
                else:
                    completed = subprocess.run(
                        cmd_args,
                        timeout=timeout,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                        env=environment,
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

        result = load_scenario_result(result_path)
        transcript = cast(dict[str, JsonValue], result.model_dump(mode="json", by_alias=True, exclude_none=True))
        config = self.backend_config.experiment(timeout, transcript)
        metrics = _result_metrics(transcript, execution_time)
        if harness_error := _harness_failure(result):
            raise AgentError(f"BCal scenario harness failure: {harness_error}", transcript=transcript, config=config, metrics=metrics)
        if result.workspace_seed != expected_seed:
            actual_hash = result.workspace_seed.aggregate_sha256 if result.workspace_seed else "missing"
            raise AgentError(
                f"BCal scenario workspace seed receipt does not match the pre-run fixture snapshot: expected {expected_seed.aggregate_sha256}, got {actual_hash}",
                transcript=transcript,
                config=config,
                metrics=metrics,
            )
        if self.backend_config.agent_runtime == BCalAgentRuntime.COPILOT_SDK and result.completed:
            _require_completed(transcript, metrics=metrics, config=config)

        tool_usage: dict[str, int] = {}
        for usage in result.tool_usage:
            tool_usage[usage.name] = tool_usage.get(usage.name, 0) + usage.started
        metrics = metrics.model_copy(update={"turn_count": result.totals.steps, "tool_usage": tool_usage})
        return AgentResult(metrics=metrics, experiment=config, transcript=transcript)


def run_bcal_scenario(
    entry: BCalScenarioEntry,
    repo_path: Path,
    backend_config: BCalBackendConfig,
) -> tuple[AgentMetrics | None, ExperimentConfiguration | None]:
    result = BCalScenarioHarness(backend_config).run(AgentRequest(task=entry, work_dir=repo_path, output_dir=repo_path))
    return result.metrics, result.experiment


def _read_transcript_after_failure(path: Path) -> dict[str, JsonValue] | None:
    try:
        payload = cast(JsonValue, json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


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
