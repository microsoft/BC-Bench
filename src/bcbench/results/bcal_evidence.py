import logging
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictInt, StringConstraints, ValidationError

logger = logging.getLogger(__name__)


class BCalExecutionIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    product_version: str = Field(min_length=1, alias="productVersion")
    source_commit_sha: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{7,64}$")] | None = Field(alias="sourceCommitSha")
    build_configuration: str = Field(min_length=1, alias="buildConfiguration")
    scenario_contract_version: Literal["1.0", "1.1"] = Field(alias="scenarioContractVersion")
    evidence_contract_version: Literal["1.0", "1.1", "1.2"] = Field(alias="evidenceContractVersion")


class _Failure(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    code: str
    message: str
    step_id: str | None = Field(default=None, alias="stepId")
    retryable: StrictBool | None = None


class _ScenarioStep(BaseModel):
    id: Literal["benchmark-prompt"]
    type: Literal["user"]
    status: Literal["succeeded", "failed"]
    compile_succeeded: StrictBool | None = Field(default=None, alias="compileSucceeded")
    failure: _Failure | None = None


class _ScenarioResult(BaseModel):
    schema_version: Literal["1.0", "1.1"] = Field(alias="schemaVersion")
    execution_identity: BCalExecutionIdentity = Field(alias="executionIdentity")
    completed: StrictBool
    steps: list[_ScenarioStep] = Field(min_length=1, max_length=1)
    evidence: JsonValue = None
    failure: _Failure | None = None


class _TraceEvent(BaseModel):
    sequence: StrictInt = Field(ge=0)
    type: str


class _CompilationEvent(_TraceEvent):
    type: Literal["compilation_attempt", "compilation_outcome"]
    scenario_step_id: Literal["benchmark-prompt"] = Field(alias="scenarioStepId")
    turn: StrictInt | None = Field(default=None, ge=0)
    iteration: StrictInt | None = Field(default=None, ge=0)
    call_id: str = Field(min_length=1, alias="callId")
    operation: Literal["compile"]
    status: Literal["started", "succeeded", "failed"]
    succeeded: StrictBool | None = None


class _Trace(BaseModel):
    contract_version: str = Field(alias="contractVersion")
    truncated: StrictBool
    omitted_event_count: StrictInt = Field(ge=0, alias="omittedEventCount")
    events: list[dict[str, JsonValue]]


class _Evidence(BaseModel):
    contract_version: str = Field(alias="contractVersion")
    execution_identity: BCalExecutionIdentity = Field(alias="executionIdentity")
    trace: _Trace


class BCalExecutionFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: Literal["bcal_scenario_result"] = "bcal_scenario_result"
    agent_authored: Literal[False] = False
    execution_identity: BCalExecutionIdentity
    scenario_completed: bool
    scenario_step_status: Literal["succeeded", "failed"]
    compile_succeeded: bool | None
    compile_evidence_source: Literal["scenario_step", "trace_latest_outcome"] | None
    scenario_failure: _Failure | None
    step_failure: _Failure | None
    evidence_status: Literal["present", "missing", "malformed"]
    trace_truncated: bool | None
    trace_omitted_event_count: int | None

    @property
    def export_metadata(self) -> dict[str, str | int | bool | None]:
        failure = self.scenario_failure or self.step_failure
        return {
            "execution_provider": "bcal",
            "execution_product_version": self.execution_identity.product_version,
            "execution_source_commit_sha": self.execution_identity.source_commit_sha,
            "execution_build_configuration": self.execution_identity.build_configuration,
            "scenario_completed": self.scenario_completed,
            "scenario_step_status": self.scenario_step_status,
            "compile_succeeded": self.compile_succeeded,
            "compile_evidence_source": self.compile_evidence_source,
            "evidence_status": self.evidence_status,
            "trace_truncated": self.trace_truncated,
            "trace_omitted_event_count": self.trace_omitted_event_count,
            "bcal_failure_code": failure.code if failure else None,
            "bcal_failure_message": failure.message if failure else None,
            "bcal_failure_step_id": failure.step_id if failure else None,
            "bcal_failure_retryable": failure.retryable if failure else None,
            "bcal_terminal_reason": failure.message if failure and failure.code == "incomplete_execution" else None,
        }


def _latest_compilation_outcome(trace: _Trace) -> bool | None:
    previous_sequence = -1
    attempts: dict[str, _CompilationEvent] = {}
    outcomes: dict[str, _CompilationEvent] = {}
    latest_attempt: _CompilationEvent | None = None
    for raw_event in trace.events:
        event: _TraceEvent = _TraceEvent.model_validate(raw_event)
        if event.sequence <= previous_sequence:
            raise ValueError("Trace event sequences must be strictly increasing")
        previous_sequence = event.sequence
        if event.type not in {"compilation_attempt", "compilation_outcome"}:
            continue
        compilation: _CompilationEvent = _CompilationEvent.model_validate(raw_event)
        if compilation.type == "compilation_attempt":
            if compilation.status != "started" or compilation.succeeded is not None or compilation.call_id in attempts:
                raise ValueError("Invalid or duplicate compilation attempt")
            attempts[compilation.call_id] = compilation
            latest_attempt = compilation
        else:
            attempt = attempts.get(compilation.call_id)
            if attempt is None or (attempt.turn, attempt.iteration) != (compilation.turn, compilation.iteration) or compilation.call_id in outcomes:
                raise ValueError("Compilation outcome does not uniquely match an earlier attempt")
            if compilation.succeeded is None or compilation.status != ("succeeded" if compilation.succeeded else "failed"):
                raise ValueError("Compilation outcome status does not match succeeded")
            outcomes[compilation.call_id] = compilation

    if latest_attempt is None:
        return None
    outcome = outcomes.get(latest_attempt.call_id)
    if outcome is None:
        logger.warning("BCal trace has no outcome for its latest compilation attempt")
        return None
    return outcome.succeeded


def _parse_evidence(result: _ScenarioResult) -> _Evidence:
    evidence: _Evidence = _Evidence.model_validate(result.evidence)
    version = result.execution_identity.evidence_contract_version
    if evidence.execution_identity != result.execution_identity or evidence.contract_version != version or evidence.trace.contract_version != version:
        raise ValueError("Evidence identity or contract version does not match the scenario")
    return evidence


def compilation_facts(transcript: dict[str, JsonValue] | None) -> BCalExecutionFacts | None:
    if transcript is None:
        return None
    try:
        result: _ScenarioResult = _ScenarioResult.model_validate(transcript)
    except ValidationError:
        logger.warning("Ignoring BCal compilation facts: invalid scenario result")
        return None

    step = result.steps[0]
    compile_succeeded = step.compile_succeeded
    source: Literal["scenario_step", "trace_latest_outcome"] | None = "scenario_step" if compile_succeeded is not None else None
    evidence_status: Literal["present", "missing", "malformed"] = "missing"
    trace_truncated: bool | None = None
    omitted_event_count: int | None = None
    if result.evidence is not None:
        try:
            evidence: _Evidence = _parse_evidence(result)
            evidence_status = "present"
            trace_truncated = evidence.trace.truncated
            omitted_event_count = evidence.trace.omitted_event_count
            if compile_succeeded is None and not trace_truncated and omitted_event_count == 0:
                compile_succeeded = _latest_compilation_outcome(evidence.trace)
                if compile_succeeded is not None:
                    source = "trace_latest_outcome"
        except ValidationError:
            evidence_status = "malformed"
            logger.warning("Ignoring BCal trace compilation facts: invalid evidence")
        except ValueError as exc:
            evidence_status = "malformed"
            logger.warning("Ignoring BCal trace compilation facts: %s", exc)

    return BCalExecutionFacts(
        execution_identity=result.execution_identity,
        scenario_completed=result.completed,
        scenario_step_status=step.status,
        compile_succeeded=compile_succeeded,
        compile_evidence_source=source,
        scenario_failure=result.failure,
        step_failure=step.failure,
        evidence_status=evidence_status,
        trace_truncated=trace_truncated,
        trace_omitted_event_count=omitted_event_count,
    )
