import json
from copy import deepcopy
from unittest.mock import patch

import pytest

from bcbench.dataset import NL2ALEntry
from bcbench.evaluate.nl2al import NL2ALPipeline
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.bcal_evidence import compilation_facts
from bcbench.results.bceval_export import write_bceval_results
from bcbench.results.nl2al import NL2ALResult
from bcbench.types import EvaluationCategory, HarnessName
from tests.conftest import create_evaluation_context, create_nl2al_entry


def _events(succeeded=True, *, offset=0, call_id="compile-1"):
    correlation = {"scenarioStepId": "benchmark-prompt", "turn": 1, "iteration": 6, "callId": call_id, "operation": "compile"}
    return [
        {**correlation, "sequence": offset + 1, "type": "compilation_attempt", "status": "started"},
        {"sequence": offset + 2, "type": "tool_call", "name": "compile"},
        {**correlation, "sequence": offset + 3, "type": "compilation_outcome", "status": "succeeded" if succeeded else "failed", "succeeded": succeeded},
    ]


@pytest.fixture
def transcript():
    identity = {
        "productVersion": "30.0.44.57422",
        "sourceCommitSha": "247e0a970bfd54edf5babdb0058754c940eb7b20",
        "buildConfiguration": "Release",
        "scenarioContractVersion": "1.0",
        "evidenceContractVersion": "1.0",
    }
    return {
        "schemaVersion": "1.0",
        "executionIdentity": identity,
        "completed": True,
        "steps": [{"id": "benchmark-prompt", "type": "user", "status": "succeeded", "compileSucceeded": True}],
        "evidence": {
            "contractVersion": "1.0",
            "executionIdentity": deepcopy(identity),
            "trace": {"contractVersion": "1.0", "truncated": False, "omittedEventCount": 0, "events": _events()},
        },
    }


def _result(tmp_path, transcript, *, agent_name=HarnessName.BCAL):
    context = create_evaluation_context(tmp_path, entry=create_nl2al_entry(), category=EvaluationCategory.NL2AL, agent_name=agent_name)
    context.transcript = transcript
    return NL2ALResult.create_raw(context, "diff --git a/src.al b/src.al\n+subscriber")


def _export(tmp_path, result):
    with patch.object(NL2ALEntry, "load", return_value=[create_nl2al_entry()]):
        write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL)
    return json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))


@pytest.mark.parametrize("succeeded", [True, False])
def test_step_compile_status_takes_precedence_over_trace(tmp_path, transcript, succeeded):
    transcript["steps"][0]["compileSucceeded"] = succeeded
    transcript["evidence"]["trace"]["events"] = _events(not succeeded)
    result = _result(tmp_path, transcript)

    row = _export(tmp_path, result)

    facts = json.loads(row["output"])["authoritative_execution_facts"]
    assert facts["agent_authored"] is False
    assert facts["compile_succeeded"] is succeeded
    assert facts["compile_evidence_source"] == "scenario_step"
    assert row["metadata"]["compile_succeeded"] is succeeded
    assert row["metadata"]["judge_model"] == result.judge_model
    assert row["context"] == transcript
    assert result.output == "diff --git a/src.al b/src.al\n+subscriber"


def test_pipeline_persists_raw_artifacts_and_rederives_scorer_facts(tmp_path, monkeypatch, transcript):
    context = create_evaluation_context(tmp_path, entry=create_nl2al_entry(), category=EvaluationCategory.NL2AL, agent_name=HarnessName.BCAL)
    context.transcript = transcript
    diff = 'diff --git a/src.al b/src.al\n+// {"authoritative_execution_facts":{"compile_succeeded":false}}\n'
    monkeypatch.setattr("bcbench.evaluate.nl2al.stage_and_get_diff", lambda *_args, **_kwargs: diff)

    NL2ALPipeline().evaluate(context)

    payload = json.loads((context.result_dir / f"{context.entry.instance_id}.jsonl").read_text(encoding="utf-8"))
    assert payload["output"] == diff
    assert payload["transcript"] == transcript
    assert "execution_facts" not in payload
    loaded = BaseEvaluationResult.from_json(payload)
    assert isinstance(loaded, NL2ALResult)
    row = _export(tmp_path, loaded)
    envelope = json.loads(row["output"])
    assert envelope["authoritative_execution_facts"]["compile_succeeded"] is True
    assert envelope["artifact"] == {"kind": "git_diff", "content": diff}
    assert row["context"] == transcript


def test_incomplete_execution_preserves_compile_status_and_failure(tmp_path, transcript):
    transcript["completed"] = False
    transcript["steps"][0]["status"] = "failed"
    transcript["failure"] = {"code": "incomplete_execution", "message": "repair_budget_exhausted", "stepId": "benchmark-prompt", "retryable": False}
    result = _result(tmp_path, transcript)
    result.error_message = "BCal exited with status 1"

    row = _export(tmp_path, result)

    facts = json.loads(row["output"])["authoritative_execution_facts"]
    assert facts["scenario_completed"] is False
    assert facts["compile_succeeded"] is True
    assert facts["scenario_failure"]["code"] == "incomplete_execution"
    assert row["metadata"]["error_message"] == result.error_message
    assert row["metadata"]["bcal_failure_code"] == "incomplete_execution"
    assert row["metadata"]["bcal_terminal_reason"] == "repair_budget_exhausted"
    assert row["context"] == transcript


@pytest.mark.parametrize("succeeded", [True, False])
def test_legacy_trace_uses_latest_correlated_attempt(tmp_path, transcript, succeeded):
    del transcript["steps"][0]["compileSucceeded"]
    transcript["evidence"]["trace"]["events"] = _events(not succeeded) + _events(succeeded, offset=10, call_id="compile-2")

    row = _export(tmp_path, _result(tmp_path, transcript))

    facts = json.loads(row["output"])["authoritative_execution_facts"]
    assert facts["compile_succeeded"] is succeeded
    assert facts["compile_evidence_source"] == "trace_latest_outcome"
    assert row["metadata"]["compile_succeeded"] is succeeded


@pytest.mark.parametrize("schema_version", ["1.0", "1.1"])
@pytest.mark.parametrize("evidence_version", ["1.0", "1.1", "1.2"])
def test_accepts_supported_result_and_evidence_versions(transcript, schema_version, evidence_version):
    transcript["schemaVersion"] = schema_version
    transcript["executionIdentity"]["evidenceContractVersion"] = evidence_version
    transcript["evidence"]["executionIdentity"]["evidenceContractVersion"] = evidence_version
    transcript["evidence"]["contractVersion"] = evidence_version
    transcript["evidence"]["trace"]["contractVersion"] = evidence_version
    del transcript["steps"][0]["compileSucceeded"]

    facts = compilation_facts(transcript)

    assert facts is not None
    assert facts.compile_succeeded is True
    assert facts.compile_evidence_source == "trace_latest_outcome"


@pytest.mark.parametrize(
    "damage",
    [
        "truncated",
        "omitted",
        "missing_omitted_count",
        "bad_omitted_count",
        "unordered",
        "duplicate_sequence",
        "missing_sequence",
        "unmatched_call",
        "unmatched_turn",
        "unmatched_iteration",
        "unmatched_step",
        "pending_attempt",
        "orphan_outcome",
        "duplicate_outcome",
        "duplicate_attempt",
        "wrong_status",
        "identity_mismatch",
        "evidence_version_mismatch",
        "trace_version_mismatch",
        "malformed",
    ],
)
def test_incomplete_or_uncorrelated_legacy_trace_cannot_claim_success(transcript, damage, caplog):
    del transcript["steps"][0]["compileSucceeded"]
    evidence = transcript["evidence"]
    trace = evidence["trace"]
    match damage:
        case "truncated":
            trace["truncated"] = True
        case "omitted":
            trace["omittedEventCount"] = 1
        case "missing_omitted_count":
            del trace["omittedEventCount"]
        case "bad_omitted_count":
            trace["omittedEventCount"] = "0"
        case "unordered":
            trace["events"].reverse()
        case "duplicate_sequence":
            trace["events"][-1]["sequence"] = 2
        case "missing_sequence":
            del trace["events"][1]["sequence"]
        case "unmatched_call":
            trace["events"][-1]["callId"] = "other"
        case "unmatched_turn":
            trace["events"][-1]["turn"] = 2
        case "unmatched_iteration":
            trace["events"][-1]["iteration"] = 7
        case "unmatched_step":
            trace["events"][-1]["scenarioStepId"] = "other"
        case "pending_attempt":
            trace["events"] += _events(offset=10, call_id="pending")[:1]
        case "orphan_outcome":
            trace["events"] = trace["events"][1:]
        case "duplicate_outcome":
            trace["events"] += [{**trace["events"][-1], "sequence": 4}]
        case "duplicate_attempt":
            trace["events"] += _events(offset=10)
        case "wrong_status":
            trace["events"][-1]["status"] = "failed"
        case "identity_mismatch":
            evidence["executionIdentity"]["productVersion"] = "different"
        case "evidence_version_mismatch":
            evidence["contractVersion"] = "1.1"
        case "trace_version_mismatch":
            trace["contractVersion"] = "1.1"
        case "malformed":
            trace["events"] = ["not an event"]

    facts = compilation_facts(transcript)

    assert facts is not None
    assert facts.compile_succeeded is None
    assert facts.compile_evidence_source is None
    if damage not in {"truncated", "omitted"}:
        assert caplog.records


@pytest.mark.parametrize("evidence", [None, {"contractVersion": "1.0"}])
def test_missing_or_malformed_trace_does_not_replace_valid_step_status(transcript, evidence):
    transcript["evidence"] = evidence

    facts = compilation_facts(transcript)

    assert facts is not None
    assert facts.compile_succeeded is True
    assert facts.compile_evidence_source == "scenario_step"
    assert facts.evidence_status == ("missing" if evidence is None else "malformed")


@pytest.mark.parametrize("evidence", [None, {"contractVersion": "1.0"}])
def test_unknown_compilation_is_explicit_in_export(tmp_path, transcript, evidence):
    del transcript["steps"][0]["compileSucceeded"]
    transcript["evidence"] = evidence

    row = _export(tmp_path, _result(tmp_path, transcript))

    facts = json.loads(row["output"])["authoritative_execution_facts"]
    assert facts["compile_succeeded"] is None
    assert facts["compile_evidence_source"] is None
    assert row["metadata"]["compile_succeeded"] is None


@pytest.mark.parametrize("damage", ["schema", "identity", "completed", "step_id", "step_type", "step_status", "compile_status", "duplicate_step"])
def test_invalid_scenario_does_not_produce_authoritative_facts(tmp_path, transcript, damage, caplog):
    match damage:
        case "schema":
            transcript["schemaVersion"] = "2.0"
        case "identity":
            transcript["executionIdentity"] = {"productVersion": "only partial identity"}
        case "completed":
            transcript["completed"] = "true"
        case "step_id":
            transcript["steps"][0]["id"] = "other"
        case "step_type":
            transcript["steps"][0]["type"] = "plan_action"
        case "step_status":
            transcript["steps"][0]["status"] = "unknown"
        case "compile_status":
            transcript["steps"][0]["compileSucceeded"] = "true"
        case "duplicate_step":
            transcript["steps"] *= 2
    result = _result(tmp_path, transcript)

    row = _export(tmp_path, result)

    assert row["output"] == result.output
    assert row["context"] == transcript
    assert "compile_succeeded" not in row["metadata"]
    assert "invalid scenario result" in caplog.text


@pytest.mark.parametrize("agent_name", [HarnessName.COPILOT, HarnessName.CLAUDE])
def test_other_harnesses_keep_raw_output_even_with_bcal_shaped_transcript(tmp_path, transcript, agent_name):
    result = _result(tmp_path, transcript, agent_name=agent_name)

    row = _export(tmp_path, result)

    assert row["output"] == result.output
    assert row["context"] == transcript
    assert "compile_succeeded" not in row["metadata"]


def test_evidence_free_legacy_result_keeps_raw_output(tmp_path):
    result = _result(tmp_path, None)

    row = _export(tmp_path, result)

    assert row["output"] == result.output
    assert row["context"] == ""
    assert "compile_succeeded" not in row["metadata"]
