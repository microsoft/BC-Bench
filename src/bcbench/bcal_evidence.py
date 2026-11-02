from __future__ import annotations

from typing import Any, Literal

from pydantic import ValidationError

from bcbench.types import BCalCompilationEvent, BCalExecutionFacts, BCalExecutionIdentity, BCalFailureFacts


def normalize_bcal_execution_facts(
    *,
    execution_identity: BCalExecutionIdentity,
    evidence: dict[str, Any] | None,
    scenario_completed: bool | None = None,
    scenario_step_status: Literal["succeeded", "failed"] | None = None,
    step_compile_succeeded: bool | None = None,
    scenario_failure: BCalFailureFacts | None = None,
    step_failure: BCalFailureFacts | None = None,
) -> BCalExecutionFacts:
    evidence_status: Literal["present", "missing", "malformed"]
    trace_truncated: bool | None = None
    compilation_events: tuple[BCalCompilationEvent, ...] = ()

    if evidence is None:
        evidence_status = "missing"
    else:
        try:
            evidence_status, trace_truncated, compilation_events = _parse_evidence(execution_identity, evidence)
        except (KeyError, TypeError, ValueError, ValidationError):
            evidence_status = "malformed"

    compile_succeeded = step_compile_succeeded
    compile_evidence_source: Literal["scenario_step", "trace_latest_outcome"] | None = None
    if step_compile_succeeded is not None:
        compile_evidence_source = "scenario_step"
    elif evidence_status == "present" and trace_truncated is False:
        outcomes = [event for event in compilation_events if event.type == "compilation_outcome"]
        if outcomes and outcomes[-1].succeeded is not None:
            compile_succeeded = outcomes[-1].succeeded
            compile_evidence_source = "trace_latest_outcome"

    return BCalExecutionFacts(
        execution_identity=execution_identity,
        scenario_completed=scenario_completed,
        scenario_step_status=scenario_step_status,
        step_compile_succeeded=step_compile_succeeded,
        compile_succeeded=compile_succeeded,
        compile_evidence_source=compile_evidence_source,
        compilation_events=compilation_events,
        scenario_failure=scenario_failure,
        step_failure=step_failure,
        evidence_status=evidence_status,
        trace_truncated=trace_truncated,
    )


def _parse_evidence(
    execution_identity: BCalExecutionIdentity,
    evidence: dict[str, Any],
) -> tuple[Literal["present"], bool, tuple[BCalCompilationEvent, ...]]:
    if evidence["contractVersion"] != execution_identity.evidence_contract_version:
        raise ValueError("Evidence contract version does not match execution identity")
    if BCalExecutionIdentity.model_validate(evidence["executionIdentity"]) != execution_identity:
        raise ValueError("Evidence execution identity does not match scenario execution identity")

    trace = evidence["trace"]
    if not isinstance(trace, dict):
        raise TypeError("Evidence trace must be an object")
    if trace["contractVersion"] != execution_identity.evidence_contract_version:
        raise ValueError("Trace contract version does not match execution identity")

    truncated = trace["truncated"]
    if not isinstance(truncated, bool):
        raise TypeError("Trace truncated must be a boolean")

    raw_events = trace["events"]
    if not isinstance(raw_events, list):
        raise TypeError("Trace events must be a list")

    events = tuple(
        sorted(
            (BCalCompilationEvent.model_validate(event) for event in raw_events if isinstance(event, dict) and event.get("type") in {"compilation_attempt", "compilation_outcome"}),
            key=lambda event: event.sequence,
        )
    )
    if any(not isinstance(event, dict) for event in raw_events):
        raise TypeError("Trace events must be objects")
    return "present", truncated, events
