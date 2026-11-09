import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from bcbench_core.agent.harness import AgentRequest
from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.exceptions import AgentError
from pydantic import ValidationError

import bcbench.evaluate.bcal_scenario as scenario_evaluation
from bcbench.agent.bcal import BCalBackendConfig
from bcbench.agent.bcal import scenario as bcal_scenario
from bcbench.dataset import BCalScenarioEntry
from bcbench.evaluate.bcal_scenario import evaluate_trace
from bcbench.results import BCalScenarioEvaluationResult, IndependentBuildResult, TraceAssertionResult
from bcbench.types import EvaluationCategory, HarnessName
from tests.conftest import create_evaluation_context


def create_bcal_scenario_entry(**overrides) -> BCalScenarioEntry:
    payload = {
        "instance_id": "bcal-scenario__test-case-1",
        "created_at": "2026-09-21",
        "environment_setup_version": "28.0",
        "project_paths": ["app"],
        "session": {
            "mode": "extension",
            "audience": "Technical",
            "page": "Item Card",
            "locale": "en-US",
            "publish": "never",
            "review": True,
        },
        "steps": [{"id": "request", "type": "user", "text": "Implement the requested feature."}],
        "interactions": [
            {
                "id": "choice",
                "match": {"questionRegex": "(?i)strategy"},
                "response": {"action": "accept", "selectedChoice": "Use an interface"},
            },
            {"id": "fallback", "match": {"default": True}, "response": {"action": "decline"}},
        ],
        "evaluation": {
            "compile_required": True,
            "artifact_assertions": [{"text": "The feature is implemented.", "level": "critical"}],
            "trace_assertions": [
                {"id": "choice-matched", "type": "interaction_matched", "interaction_id": "choice", "expected": "Use an interface"},
                {"id": "ask-first", "type": "tool_order", "before": "ask_user", "after": "write_file"},
                {"id": "no-publish", "type": "forbidden_tool", "tool": "publish"},
            ],
            "forbidden_assertions": [],
            "runtime_verification": None,
        },
    }
    return BCalScenarioEntry.model_validate(payload | overrides)


def scenario_result_payload(*, completed: bool = True) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "completed": completed,
        "steps": [
            {
                "id": "request",
                "type": "user",
                "status": "success",
                "assistantText": "Implemented",
                "compileSucceeded": True,
                "tokens": {"input": 10, "output": 20},
                "durationMs": 100,
                "toolUsage": [{"name": "write_file", "started": 1, "completed": 1, "succeeded": 1, "failed": 0}],
                "failure": None,
            }
        ],
        "interactions": [
            {
                "sequence": 1,
                "ruleId": "choice",
                "matched": True,
                "usedDefault": False,
                "request": {"question": "Which strategy?", "choices": ["Use an interface"]},
                "match": {"questionRegex": "(?i)strategy"},
                "response": {"action": "accept", "selectedChoice": "Use an interface", "selectedIndex": 0},
                "failure": None,
            }
        ],
        "toolUsage": [{"name": "write_file", "started": 1, "completed": 1, "succeeded": 1, "failed": 0}],
        "evidence": {
            "contractVersion": "1.0",
            "trace": {
                "events": [
                    {"type": "tool", "name": "write_file", "sequence": 2},
                ]
            },
        },
        "totals": {
            "steps": 1,
            "successfulSteps": 1,
            "failedSteps": 0,
            "inputTokens": 10,
            "outputTokens": 20,
            "toolCallsStarted": 1,
            "toolCallsCompleted": 1,
            "durationMs": 100,
        },
        "export": {"attempted": True, "success": True, "path": "app", "filesExported": 1, "message": None},
        "failure": None,
    }


def _arg_path(args: list[str], flag: str) -> Path:
    return Path(next(arg.removeprefix(f"{flag}=") for arg in args if arg.startswith(f"{flag}=")))


def test_execution_manifest_redacts_hidden_evaluation(tmp_path: Path):
    entry = create_bcal_scenario_entry()
    path = tmp_path / "execution.json"

    bcal_scenario.write_execution_manifest(entry, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == "1.0"
    assert set(payload) == {"schemaVersion", "session", "steps", "interactions"}
    assert payload["session"]["review"] is True
    assert payload["interactions"][0]["response"]["selectedChoice"] == "Use an interface"
    assert "evaluation" not in path.read_text(encoding="utf-8")


def test_scenario_schema_rejects_unmatched_interaction_rule():
    entry = create_bcal_scenario_entry()
    payload = entry.model_dump(mode="json", by_alias=True)
    payload["interactions"][0]["match"] = {}

    with pytest.raises(ValidationError, match="requires questionRegex"):
        BCalScenarioEntry.model_validate(payload)


def test_scenario_schema_requires_final_default_interaction():
    entry = create_bcal_scenario_entry()
    payload = entry.model_dump(mode="json", by_alias=True)
    payload["interactions"] = payload["interactions"][:-1]

    with pytest.raises(ValidationError, match="default rule"):
        BCalScenarioEntry.model_validate(payload)


def test_run_scenario_uses_contract_and_collects_metrics(tmp_path: Path):
    entry = create_bcal_scenario_entry()
    (tmp_path / ".bcal-symbols" / ".alpackages").mkdir(parents=True)
    captured: list[str] = []

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        captured.extend(args)
        _arg_path(args, "--result").write_text(json.dumps(scenario_result_payload()), encoding="utf-8")
        return subprocess.CompletedProcess(args, 1, stdout="scenario failed after preserving result", stderr="")

    with (
        patch.object(bcal_scenario, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
        patch.object(subprocess, "run", side_effect=fake_run),
    ):
        result = bcal_scenario.BCalScenarioHarness(
            BCalBackendConfig(command="python bridge.py", model="gpt-5"),
        ).run(
            AgentRequest(task=entry, work_dir=tmp_path, output_dir=tmp_path),
        )

    assert _arg_path(captured, "--scenario").name == "execution.json"
    assert _arg_path(captured, "--result").name == "evaluation-run.json"
    assert _arg_path(captured, "--exportfolder").name == "app"
    assert result.metrics is not None
    assert result.metrics.execution_time is not None
    assert result.transcript is not None
    assert bcal_scenario.BCalScenarioRunResult.model_validate(result.transcript).totals.input_tokens == 10


def test_nonzero_exit_without_result_is_harness_failure(tmp_path: Path):
    entry = create_bcal_scenario_entry()
    (tmp_path / ".bcal-symbols" / ".alpackages").mkdir(parents=True)

    with (
        patch.object(bcal_scenario, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
        patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(["bcal"], 2, stdout="", stderr="bad contract")),
        pytest.raises(AgentError, match=r"without writing evaluation-run\.json"),
    ):
        bcal_scenario.BCalScenarioHarness(
            BCalBackendConfig(command="python bridge.py"),
        ).run(
            AgentRequest(task=entry, work_dir=tmp_path, output_dir=tmp_path),
        )


def test_export_failure_in_structured_result_is_harness_failure(tmp_path: Path):
    entry = create_bcal_scenario_entry()
    (tmp_path / ".bcal-symbols" / ".alpackages").mkdir(parents=True)
    payload = scenario_result_payload(completed=False)
    payload["export"] = {"attempted": True, "success": False, "path": None, "filesExported": 0, "message": "export failed"}

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        _arg_path(args, "--result").write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

    with (
        patch.object(bcal_scenario, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
        patch.object(subprocess, "run", side_effect=fake_run),
        pytest.raises(AgentError, match="harness failure: export failed"),
    ):
        bcal_scenario.BCalScenarioHarness(
            BCalBackendConfig(command="python bridge.py"),
        ).run(
            AgentRequest(task=entry, work_dir=tmp_path, output_dir=tmp_path),
        )


def test_trace_uses_transcript_evidence_order_and_confirmed_choice():
    entry = create_bcal_scenario_entry()
    result = bcal_scenario.BCalScenarioRunResult.model_validate(scenario_result_payload())

    assertions = evaluate_trace(entry, result)

    assert all(assertion.passed for assertion in assertions)


def test_pilot_datasets_have_expected_entries_and_hidden_contracts():
    scenarios = BCalScenarioEntry.load(EvaluationCategory.BCAL_SCENARIO.dataset_path())
    features = BCalScenarioEntry.load(EvaluationCategory.BCAL_FEATURE.dataset_path())

    assert {entry.instance_id for entry in scenarios} == {
        "bcal-scenario__integration-choice-1",
        "bcal-scenario__explicit-plan-first-1",
    }
    assert [entry.instance_id for entry in features] == ["bcal-feature__warehouse-inventory-risk-1"]
    assert len(features[0].evaluation.artifact_assertions) >= 12
    assert features[0].session.publish == "never"
    assert features[0].evaluation.runtime_verification is None
    assert any(assertion["text"].startswith("Forbidden behavior is absent:") for assertion in features[0].get_expected_output()["assertions"])


def test_independent_build_is_explicitly_not_attempted_without_compiler(tmp_path: Path):
    app_folder = tmp_path / "app"
    app_folder.mkdir()
    (app_folder / "Feature.al").write_text("codeunit 50100 Feature { }", encoding="utf-8")

    with patch.object(scenario_evaluation.shutil, "which", return_value=None):
        result = scenario_evaluation._compile_exported_project(app_folder, tmp_path / ".alpackages")

    assert result.status == "not_attempted"
    assert result.passed is False
    assert "'al' compiler is not installed" in (result.message or "")


def test_structured_result_exposes_deterministic_metrics(tmp_path: Path):
    entry = create_bcal_scenario_entry()
    context = create_evaluation_context(
        tmp_path,
        entry=entry,
        agent_name=HarnessName.BCAL,
        category=EvaluationCategory.BCAL_SCENARIO,
    )
    context.metrics = AgentMetrics(execution_time=1, prompt_tokens=10, completion_tokens=20, turn_count=1, tool_usage={"write_file": 1})

    result = BCalScenarioEvaluationResult.create(
        context,
        output="packet",
        scenario_completed=True,
        independent_build=IndependentBuildResult(status="not_attempted", message="No compiler"),
        trace_assertions=[TraceAssertionResult(assertion_id="trace", passed=True, message="passed")],
        runtime_status=None,
    )

    assert result.trace_compliance is True
    assert result.category_metrics == {
        "scenario_completed": True,
        "independent_build": False,
        "independent_build_attempted": False,
        "trace_compliance": True,
    }
    assert BCalScenarioEvaluationResult.model_validate_json(result.model_dump_json()) == result


def test_bcal_workflow_accepts_both_advanced_categories():
    workflow = Path(".github/workflows/bcal-evaluation.yml").read_text(encoding="utf-8")

    assert '- "bcal-scenario"' in workflow
    assert '- "bcal-feature"' in workflow
    assert "--category \"${{ inputs.category || 'bcal-scenario' }}\"" in workflow
    assert "path: ${{ env.EVALUATION_RESULTS_DIR }}/**" in workflow
