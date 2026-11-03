import json
import shutil
import subprocess
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

import bcbench.evaluate.bcal_scenario as scenario_evaluation
from bcbench.agent.bcal import BCalBackendConfig, bc_eval_llm_api_bridge
from bcbench.agent.bcal import scenario as bcal_scenario
from bcbench.dataset import BCalScenarioEntry, BCalTraceAssertion
from bcbench.evaluate.bcal_scenario import evaluate_trace
from bcbench.exceptions import AgentError
from bcbench.results import BCalScenarioEvaluationResult, IndependentBuildResult, TraceAssertionResult
from bcbench.types import AgentHarness, AgentMetrics, BCalLLMBackend, EvaluationCategory
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


def scenario_result_payload(*, completed: bool = True) -> dict:
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
        "sessionArchive": {
            "attempted": True,
            "success": True,
            "path": "session",
            "fileName": "session.zip",
            "entriesExported": 2,
            "chatEntryPath": "chat.json",
            "message": None,
        },
        "failure": None,
    }


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


@pytest.mark.parametrize("path", ["../outside.al", "C:\\outside.al", "folder\\outside.al"])
def test_scenario_schema_rejects_workspace_path_traversal(path: str):
    entry = create_bcal_scenario_entry()
    payload = entry.model_dump(mode="json", by_alias=True)
    payload["workspace_files"] = {path: "codeunit 50100 Outside { }"}

    with pytest.raises(ValidationError, match="stay within the exported app folder"):
        BCalScenarioEntry.model_validate(payload)


def test_llm_api_bridge_accepts_windows_utf8_bom():
    request = {"model": "gpt-55-chat", "messages": [{"role": "user", "content": "hello"}]}
    stream = BytesIO(b"\xef\xbb\xbf" + json.dumps(request).encode())

    assert bc_eval_llm_api_bridge._load_request(stream) == request


def test_run_scenario_uses_contract_and_collects_metrics(tmp_path: Path):
    entry = create_bcal_scenario_entry()
    (tmp_path / ".bcal-symbols" / ".alpackages").mkdir(parents=True)
    captured: list[str] = []

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess:
        captured.extend(args)
        result_path = Path(args[args.index("--result") + 1])
        result_path.write_text(json.dumps(scenario_result_payload()), encoding="utf-8")
        return subprocess.CompletedProcess(args, 1, stdout="scenario failed after preserving result", stderr="")

    with (
        patch.object(bcal_scenario, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
        patch.object(subprocess, "run", side_effect=fake_run),
    ):
        metrics, _ = bcal_scenario.run_bcal_scenario(
            entry,
            tmp_path,
            BCalBackendConfig(backend=BCalLLMBackend.EXTERNAL_COMMAND, command="python bridge.py", model="gpt-5"),
        )

    assert captured[captured.index("--scenario") + 1].endswith("execution.json")
    assert captured[captured.index("--result") + 1].endswith("evaluation-run.json")
    assert captured[captured.index("--exportfolder") + 1].endswith("app")
    assert metrics.prompt_tokens == 10
    assert metrics.completion_tokens == 20
    assert metrics.turn_count == 1
    assert metrics.tool_usage == {"write_file": 1}


def test_nonzero_exit_without_result_is_harness_failure(tmp_path: Path):
    entry = create_bcal_scenario_entry()
    (tmp_path / ".bcal-symbols" / ".alpackages").mkdir(parents=True)

    with (
        patch.object(bcal_scenario, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
        patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(["bcal"], 2, stdout="", stderr="bad contract")),
        pytest.raises(AgentError, match=r"without writing evaluation-run\.json"),
    ):
        bcal_scenario.run_bcal_scenario(
            entry,
            tmp_path,
            BCalBackendConfig(backend=BCalLLMBackend.EXTERNAL_COMMAND, command="python bridge.py"),
        )


def test_export_failure_in_structured_result_is_harness_failure(tmp_path: Path):
    entry = create_bcal_scenario_entry()
    (tmp_path / ".bcal-symbols" / ".alpackages").mkdir(parents=True)
    payload = scenario_result_payload(completed=False)
    payload["export"] = {"attempted": True, "success": False, "path": None, "filesExported": 0, "message": "export failed"}

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess:
        Path(args[args.index("--result") + 1]).write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

    with (
        patch.object(bcal_scenario, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
        patch.object(subprocess, "run", side_effect=fake_run),
        pytest.raises(AgentError, match="harness failure: export failed"),
    ):
        bcal_scenario.run_bcal_scenario(
            entry,
            tmp_path,
            BCalBackendConfig(backend=BCalLLMBackend.EXTERNAL_COMMAND, command="python bridge.py"),
        )


def test_trace_uses_chat_order_and_confirmed_choice(tmp_path: Path):
    entry = create_bcal_scenario_entry()
    result = bcal_scenario.BCalScenarioRunResult.model_validate(scenario_result_payload())
    chat = tmp_path / "chat.json"
    chat.write_text(
        json.dumps(
            [
                {"type": "tool_call", "toolName": "ask_user", "sequence": 1},
                {"type": "tool_call", "toolName": "write_file", "sequence": 2},
            ]
        ),
        encoding="utf-8",
    )

    assertions = evaluate_trace(entry, result, chat)

    assert all(assertion.passed for assertion in assertions)


def test_trace_prefers_gate_a_canonical_trace(tmp_path: Path):
    entry = create_bcal_scenario_entry()
    payload = scenario_result_payload()
    payload["executionIdentity"] = {
        "productVersion": "30.0.44.65502-beta",
        "sourceCommitSha": "0123456789abcdef",
        "buildConfiguration": "Release",
        "scenarioContractVersion": "1.0",
        "evidenceContractVersion": "1.1",
    }
    payload["evidence"] = {
        "contractVersion": "1.1",
        "promptEvidence": {"compositions": [{"id": "system"}], "uses": [{"id": "system"}]},
        "trace": {
            "contractVersion": "1.1",
            "eventLimit": 10000,
            "truncated": False,
            "omittedEventCount": 0,
            "events": [
                {"type": "tool_call", "toolName": "ask_user", "sequence": 1},
                {"type": "tool_call", "toolName": "write_file", "sequence": 2},
            ],
        },
    }
    result = bcal_scenario.BCalScenarioRunResult.model_validate(payload)
    chat = tmp_path / "chat.json"
    chat.write_text(json.dumps([{"type": "tool_call", "toolName": "publish", "sequence": 0}]), encoding="utf-8")

    assertions = evaluate_trace(entry, result, chat)

    assert all(assertion.passed for assertion in assertions)
    assert result.prompt_evidence == payload["evidence"]["promptEvidence"]
    assert result.canonical_trace == payload["evidence"]["trace"]


def test_changed_paths_and_rejected_interactions_are_behavioral_assertions():
    payload = scenario_result_payload()
    payload["interactions"][0]["response"] = {"action": "decline"}
    result = bcal_scenario.BCalScenarioRunResult.model_validate(payload)

    rejected = scenario_evaluation.evaluate_trace_assertion(
        BCalTraceAssertion(id="rejected", type="interaction_rejected", interaction_id="choice"),
        result,
        None,
        [],
    )
    unchanged = scenario_evaluation.evaluate_trace_assertion(
        BCalTraceAssertion(id="unchanged", type="changed_paths", paths=[]),
        result,
        None,
        [],
    )

    assert rejected.passed is True
    assert unchanged.passed is True


def test_pilot_datasets_have_expected_entries_and_hidden_contracts():
    scenarios = BCalScenarioEntry.load(EvaluationCategory.BCAL_SCENARIO.dataset_path)
    features = BCalScenarioEntry.load(EvaluationCategory.BCAL_FEATURE.dataset_path)

    scenario_ids = {entry.instance_id for entry in scenarios}
    assert {
        "bcal-scenario__integration-choice-1",
        "bcal-scenario__explicit-plan-first-1",
    } < scenario_ids
    assert {
        "bcal-scenario__authority-direct-and-corrected-scope-1",
        "bcal-scenario__authority-rejected-permission-1",
        "bcal-scenario__authority-retained-intent-1",
        "bcal-scenario__authority-untrusted-evidence-1",
    } < scenario_ids
    assert [entry.instance_id for entry in features] == ["bcal-feature__warehouse-inventory-risk-1"]
    assert len(features[0].evaluation.artifact_assertions) >= 12
    assert features[0].session.publish == "never"
    assert features[0].evaluation.runtime_verification is None
    assert any(assertion["text"].startswith("Forbidden behavior is absent:") for assertion in features[0].get_expected_output()["assertions"])
    authority_entries = [entry for entry in scenarios if entry.metadata.area == "authority-contract"]
    assert all(entry.workspace_files for entry in authority_entries)
    assert any(len(entry.steps) >= 12 for entry in authority_entries)


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
        agent_name=AgentHarness.BCAL,
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


def test_structured_result_exports_gate_a_metadata(tmp_path: Path):
    entry = create_bcal_scenario_entry()
    context = create_evaluation_context(
        tmp_path,
        entry=entry,
        agent_name=AgentHarness.BCAL,
        category=EvaluationCategory.BCAL_SCENARIO,
    )
    result = BCalScenarioEvaluationResult.create(
        context,
        output="packet",
        scenario_completed=True,
        independent_build=IndependentBuildResult(status="passed"),
        trace_assertions=[],
        runtime_status=None,
        execution_identity={
            "productVersion": "30.0.44.65502-beta",
            "sourceCommitSha": "0123456789abcdef",
            "evidenceContractVersion": "1.1",
        },
        prompt_evidence={"compositions": [{"id": "system"}], "uses": [{"id": "system"}, {"id": "user"}]},
        canonical_trace={"truncated": False, "events": [{"type": "tool_call"}]},
    )

    assert result.export_metadata["bcal_product_version"] == "30.0.44.65502-beta"
    assert result.export_metadata["prompt_composition_count"] == 1
    assert result.export_metadata["prompt_use_count"] == 2
    assert result.export_metadata["canonical_trace_event_count"] == 1
    assert result.export_metadata["canonical_trace_truncated"] is False


def test_bcal_workflow_accepts_both_advanced_categories():
    workflow = Path(".github/workflows/bcal-evaluation.yml").read_text(encoding="utf-8")

    assert '- "bcal-scenario"' in workflow
    assert '- "bcal-feature"' in workflow
    assert "--category \"${{ inputs.category || 'bcal-scenario' }}\"" in workflow
    assert "path: ${{ env.EVALUATION_RESULTS_DIR }}/**" in workflow


def test_authority_experiment_selector_excludes_control_tower():
    selector_path = Path("dataset/experiments/bcal_authority_provenance_v1.json")
    selector = json.loads(selector_path.read_text(encoding="utf-8"))
    scenarios = BCalScenarioEntry.load(EvaluationCategory.BCAL_SCENARIO.dataset_path)
    scenario_ids = {entry.instance_id for entry in scenarios}
    gold_ids = {json.loads(line)["instance_id"] for line in Path(selector["ordinary_quality"]["dataset_file"]).read_text(encoding="utf-8").splitlines() if line.strip()}
    excluded = {entry["instance_id"] for entry in selector["excluded_entries"]}
    control_tower = "nl2al__collected-sales-operations-control-tower-1"

    assert selector["github_identity"] == "esbenk"
    assert selector["repeat_count"] == 2
    assert selector["packages"]["baseline"]["installed_identity"] == "30.0.44.65502+bdc5dc2be9bd7b59eaa1f16592604590be9621bf"
    assert selector["packages"]["candidate"]["installed_identity"] == "30.0.45.46749+30d9e59980a978c19b4a7569fb521ce644255a53"
    assert selector["packages"]["candidate"]["nupkg_sha256"] == "2b5eb42e42f6a40e7447f67d741adac924379606c90240051acd445715eb99d6"
    assert selector["execution"] == {
        "backend": "external-command",
        "model": "gpt-55-chat",
        "bridge": "src/bcbench/agent/bcal/bc_eval_llm_api_bridge.py",
        "bridge_package": "bc-eval==0.6.1",
        "bc_version": "28.0",
        "symbol_cache": "C:\\bcartifacts.cache",
    }
    assert set(selector["authority"]["entries"]) <= scenario_ids
    assert len(selector["authority"]["entries"]) == 4
    assert len(gold_ids) == selector["ordinary_quality"]["expected_entry_count"] == 110
    assert excluded == {control_tower}
    assert control_tower not in selector["authority"]["entries"]
    assert control_tower not in gold_ids
    assert selector["excluded_entries"][0]["include_in_promotion_scoring"] is False


def test_authority_experiment_runner_uses_one_shared_selector():
    script = Path("scripts/Run-BCalAuthorityExperiment.ps1").read_text(encoding="utf-8")

    assert "bcal_authority_provenance_v1.json" in script
    assert "$entries = @($entries | Where-Object { $_ -notin $excludedEntries })" in script
    assert '"selection.json"' in script
    assert "promotion_entries = $entries" in script
    assert "Expected BCal identity" in script
    assert '$env:PATH = "$ToolPath;$env:PATH"' in script
    assert "gh auth status --hostname github.com --active --json hosts" in script
    assert "BC-Bench repository operations require" in script
    assert "BCAL_LLM_COMMAND for the fixed external-command backend" in script
    assert "symbols under $symbolRoot" in script
    assert "--repo-path $workspace" in script
    assert "--run-id $entry" not in script
    assert '$aggregateRun = Join-Path $runOutput "bcal_test_run"' in script
    assert '$caseOutput = Join-Path $OutputDir "case-results\\$Variant-$Lane-r$repeat\\$entry"' in script
    assert '"Publish-BCalCaseResults.ps1"' in script
    assert "foreach ($repeat in 1..$config.repeat_count)" in script
    assert "& python -m uv run bcbench evaluate bcal" in script


def test_authority_experiment_publishes_all_case_results(tmp_path: Path):
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is required to exercise the experiment result publisher.")

    publisher = Path(__file__).parents[1] / "scripts" / "Publish-BCalCaseResults.ps1"
    aggregate = tmp_path / "variant-authority-r1" / "bcal_test_run"
    entries = ("authority-case-1", "authority-case-2")

    for entry in entries:
        case_run = tmp_path / "case-results" / entry / "bcal_test_run"
        artifacts = case_run / "artifacts"
        artifacts.mkdir(parents=True)
        (case_run / f"{entry}.jsonl").write_text(f'{{"instance_id":"{entry}"}}\n')
        (artifacts / f"{entry}-workspace.zip").write_bytes(entry.encode())

        subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-File",
                str(publisher),
                "-CaseRun",
                str(case_run),
                "-AggregateRun",
                str(aggregate),
                "-Entry",
                entry,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    assert sorted(path.name for path in aggregate.glob("*.jsonl")) == [f"{entry}.jsonl" for entry in entries]
    assert sorted(path.name for path in (aggregate / "artifacts").glob("*.zip")) == [f"{entry}-workspace.zip" for entry in entries]

    duplicate = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-File",
            str(publisher),
            "-CaseRun",
            str(tmp_path / "case-results" / entries[0] / "bcal_test_run"),
            "-AggregateRun",
            str(aggregate),
            "-Entry",
            entries[0],
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert duplicate.returncode != 0
    assert "BCal experiment output collision" in duplicate.stderr
