import json
from unittest.mock import patch

import pytest

from bcbench.bcal_evidence import normalize_bcal_execution_facts
from bcbench.dataset import NL2ALEntry
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.bceval_export import write_bceval_results
from bcbench.types import AgentHarness, BCalExecutionIdentity, BCalScenarioFailure, EvaluationCategory
from tests.conftest import create_evaluation_context, create_nl2al_entry


def _write_entry(path, entry):
    path.write_text(entry.model_dump_json() + "\n", encoding="utf-8")


def _entry() -> NL2ALEntry:
    return create_nl2al_entry(nl_prompt="Gold prompt")


def _result_for(entry: NL2ALEntry, tmp_path, agent_name: AgentHarness = AgentHarness.BCAL):
    context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.NL2AL, agent_name=agent_name)
    return context, JudgeBasedEvaluationResult.create_raw(context, "generated AL")


def _execution_identity() -> BCalExecutionIdentity:
    return BCalExecutionIdentity(
        productVersion="30.0.44.57422",
        sourceCommitSha="247e0a970bfd54edf5babdb0058754c940eb7b20",
        buildConfiguration="Release",
        scenarioContractVersion="1.0",
        evidenceContractVersion="1.0",
    )


def _compilation_evidence(*, succeeded: bool = True, truncated: bool = False, events: list[dict[str, object]] | None = None):
    identity = _execution_identity()
    return {
        "contractVersion": "1.0",
        "executionIdentity": identity.model_dump(mode="json", by_alias=True),
        "promptEvidence": {"compositions": [], "uses": []},
        "trace": {
            "contractVersion": "1.0",
            "eventLimit": 10000,
            "truncated": truncated,
            "omittedEventCount": 0,
            "events": events
            if events is not None
            else [
                {
                    "sequence": 30,
                    "type": "compilation_attempt",
                    "scenarioStepId": "benchmark-prompt",
                    "turn": 1,
                    "iteration": 6,
                    "callId": "call-compile",
                    "operation": "compile",
                    "status": "started",
                },
                {
                    "sequence": 33,
                    "type": "compilation_outcome",
                    "scenarioStepId": "benchmark-prompt",
                    "turn": 1,
                    "iteration": 6,
                    "callId": "call-compile",
                    "operation": "compile",
                    "status": "succeeded" if succeeded else "failed",
                    "succeeded": succeeded,
                },
            ],
        },
    }


PURCHASE_VAT_COMPILATION_EVENTS: dict[str, list[dict[str, object]]] = {
    "81a91f6e-3556-45b4-8c94-dea59a335f7d": [
        {
            "type": "compilation_attempt",
            "operation": "compile",
            "iteration": 7,
            "sequence": 38,
            "status": "started",
            "callId": "call_DqNz2VhguHyEJhzeUClKFJ1i",
            "turn": 1,
            "scenarioStepId": "benchmark-prompt",
        },
        {
            "type": "compilation_outcome",
            "operation": "compile",
            "iteration": 7,
            "sequence": 41,
            "status": "succeeded",
            "succeeded": True,
            "callId": "call_DqNz2VhguHyEJhzeUClKFJ1i",
            "turn": 1,
            "scenarioStepId": "benchmark-prompt",
        },
        {
            "type": "deployment_transition",
            "operation": "compile",
            "iteration": 7,
            "sequence": 42,
            "status": "completed",
            "fromState": "none",
            "toState": "compiled_unpublished",
            "callId": "call_DqNz2VhguHyEJhzeUClKFJ1i",
            "turn": 1,
            "scenarioStepId": "benchmark-prompt",
        },
    ],
    "83808c80-1d98-42ed-bcde-bf60dadcb407": [
        {
            "type": "compilation_attempt",
            "operation": "compile",
            "iteration": 5,
            "sequence": 24,
            "status": "started",
            "callId": "call_LghN2dMhn0YPZ93eb4BEr6vi",
            "turn": 1,
            "scenarioStepId": "benchmark-prompt",
        },
        {
            "type": "compilation_outcome",
            "operation": "compile",
            "iteration": 5,
            "sequence": 27,
            "status": "failed",
            "succeeded": False,
            "callId": "call_LghN2dMhn0YPZ93eb4BEr6vi",
            "turn": 1,
            "scenarioStepId": "benchmark-prompt",
        },
        {
            "type": "compilation_attempt",
            "operation": "compile",
            "iteration": 7,
            "sequence": 34,
            "status": "started",
            "callId": "call_Y52mN1Z8Ubf7OOulUuwTjqQH",
            "turn": 1,
            "scenarioStepId": "benchmark-prompt",
        },
        {
            "type": "compilation_outcome",
            "operation": "compile",
            "iteration": 7,
            "sequence": 37,
            "status": "succeeded",
            "succeeded": True,
            "callId": "call_Y52mN1Z8Ubf7OOulUuwTjqQH",
            "turn": 1,
            "scenarioStepId": "benchmark-prompt",
        },
        {
            "type": "deployment_transition",
            "operation": "compile",
            "iteration": 7,
            "sequence": 38,
            "status": "completed",
            "fromState": "none",
            "toState": "compiled_unpublished",
            "callId": "call_Y52mN1Z8Ubf7OOulUuwTjqQH",
            "turn": 1,
            "scenarioStepId": "benchmark-prompt",
        },
    ],
}


@pytest.mark.parametrize("compile_succeeded", [True, False])
def test_bcal_export_wraps_diff_with_authoritative_execution_facts(tmp_path, compile_succeeded):
    entry = _entry()
    path = tmp_path / "nl2al.jsonl"
    _write_entry(path, entry)
    context, result = _result_for(entry, tmp_path)
    identity = _execution_identity()
    evidence = _compilation_evidence(succeeded=compile_succeeded)
    context.execution_identity = identity
    context.evidence = evidence
    context.execution_facts = normalize_bcal_execution_facts(
        execution_identity=identity,
        evidence=evidence,
        scenario_completed=compile_succeeded,
        scenario_step_status="succeeded" if compile_succeeded else "failed",
        step_compile_succeeded=compile_succeeded,
    )
    result = JudgeBasedEvaluationResult.create_raw(context, "diff --git a/src.al b/src.al\n+subscriber")

    with patch.object(EvaluationCategory, "dataset_path", return_value=path):
        write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL)

    payload = json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))
    scorer_output = json.loads(payload["output"])
    assert scorer_output["artifact"] == {
        "kind": "git_diff",
        "content": "diff --git a/src.al b/src.al\n+subscriber",
    }
    assert scorer_output["authoritative_execution_facts"]["agent_authored"] is False
    assert scorer_output["authoritative_execution_facts"]["compile_succeeded"] is compile_succeeded
    assert payload["context"] == evidence
    assert payload["metadata"]["compile_succeeded"] is compile_succeeded
    assert payload["metadata"]["compile_evidence_source"] == "scenario_step"


def test_incomplete_bcal_export_preserves_failure_metadata_and_wraps_generated_diff(tmp_path):
    entry = _entry()
    path = tmp_path / "nl2al.jsonl"
    _write_entry(path, entry)
    context, _ = _result_for(entry, tmp_path)
    identity = _execution_identity()
    evidence = _compilation_evidence(succeeded=True)
    context.execution_identity = identity
    context.evidence = evidence
    context.bcal_failure = BCalScenarioFailure(
        code="incomplete_execution",
        message="repair_budget_exhausted",
        stepId="benchmark-prompt",
        retryable=False,
    )
    context.execution_facts = normalize_bcal_execution_facts(
        execution_identity=identity,
        evidence=evidence,
        scenario_completed=False,
        scenario_step_status="failed",
        step_compile_succeeded=True,
    )
    stored_diff = "diff --git a/src.al b/src.al\n+incomplete subscriber"
    result = JudgeBasedEvaluationResult.create_failure(context, output=stored_diff, error_message="BCal scenario exited with status 1")

    with patch.object(EvaluationCategory, "dataset_path", return_value=path):
        write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL)

    payload = json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))
    scorer_output = json.loads(payload["output"])
    assert scorer_output["artifact"] == {"kind": "git_diff", "content": stored_diff}
    assert scorer_output["authoritative_execution_facts"]["compile_succeeded"] is True
    assert scorer_output["authoritative_execution_facts"]["scenario_completed"] is False
    assert payload["context"] == evidence
    assert payload["metadata"]["bcal_failure_code"] == "incomplete_execution"
    assert payload["metadata"]["bcal_terminal_reason"] == "repair_budget_exhausted"


@pytest.mark.parametrize(("eval_run_id", "expected_outcomes"), [("81a91f6e-3556-45b4-8c94-dea59a335f7d", [True]), ("83808c80-1d98-42ed-bcde-bf60dadcb407", [False, True])])
def test_bcal_export_derives_purchase_vat_legacy_trace_facts_for_rescoring(tmp_path, eval_run_id, expected_outcomes):
    entry = _entry()
    path = tmp_path / "nl2al.jsonl"
    _write_entry(path, entry)
    _, result = _result_for(entry, tmp_path)
    stored_diff = "diff --git a/src.al b/src.al\n+subscriber"
    result.output = stored_diff
    result.execution_identity = _execution_identity()
    result.evidence = _compilation_evidence(events=PURCHASE_VAT_COMPILATION_EVENTS[eval_run_id])

    with patch.object(EvaluationCategory, "dataset_path", return_value=path):
        write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL)

    payload = json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))
    scorer_output = json.loads(payload["output"])
    facts = scorer_output["authoritative_execution_facts"]
    assert facts["scenario_completed"] is None
    assert facts["compile_succeeded"] is True
    assert facts["compile_evidence_source"] == "trace_latest_outcome"
    assert [event["succeeded"] for event in facts["compilation_events"] if event["type"] == "compilation_outcome"] == expected_outcomes
    assert scorer_output["artifact"] == {"kind": "git_diff", "content": stored_diff}
    assert payload["context"] == result.evidence


def test_bcal_export_does_not_claim_compile_success_from_missing_or_malformed_evidence(tmp_path):
    entry = _entry()
    path = tmp_path / "nl2al.jsonl"
    _write_entry(path, entry)
    identity = _execution_identity()

    for name, evidence in (("missing", None), ("malformed", {"contractVersion": "1.0"})):
        context, _ = _result_for(entry, tmp_path)
        context.execution_identity = identity
        context.evidence = evidence
        context.execution_facts = normalize_bcal_execution_facts(
            execution_identity=identity,
            evidence=evidence,
            scenario_completed=True,
            scenario_step_status="succeeded",
        )
        result = JudgeBasedEvaluationResult.create_raw(context, "generated AL")

        with patch.object(EvaluationCategory, "dataset_path", return_value=path):
            write_bceval_results([result], tmp_path, "run", f"{name}.jsonl", EvaluationCategory.NL2AL)

        payload = json.loads((tmp_path / f"{name}.jsonl").read_text(encoding="utf-8"))
        facts = json.loads(payload["output"])["authoritative_execution_facts"]
        assert facts["evidence_status"] == name
        assert facts["compile_succeeded"] is None
        assert payload["context"] == (evidence if evidence is not None else "")


def test_non_bcal_nl2al_export_remains_byte_compatible(tmp_path):
    entry = _entry()
    path = tmp_path / "nl2al.jsonl"
    _write_entry(path, entry)
    context, result = _result_for(entry, tmp_path, agent_name=AgentHarness.COPILOT)
    context.evidence = {"unexpected": "context"}
    result = JudgeBasedEvaluationResult.create_raw(context, "generated AL")

    with patch.object(EvaluationCategory, "dataset_path", return_value=path):
        write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL)

    payload = json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))
    assert payload["output"] == "generated AL"
    assert payload["context"] == {"unexpected": "context"}
    assert "compile_succeeded" not in payload["metadata"]


def test_bcal_export_rejects_execution_facts_with_different_identity(tmp_path):
    entry = _entry()
    path = tmp_path / "nl2al.jsonl"
    _write_entry(path, entry)
    context, _ = _result_for(entry, tmp_path)
    context.execution_identity = _execution_identity()
    context.execution_facts = normalize_bcal_execution_facts(
        execution_identity=_execution_identity().model_copy(update={"product_version": "different"}),
        evidence=None,
    )
    result = JudgeBasedEvaluationResult.create_raw(context, "generated AL")

    with (
        patch.object(EvaluationCategory, "dataset_path", return_value=path),
        pytest.raises(ValueError, match="execution facts do not match"),
    ):
        write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL)
