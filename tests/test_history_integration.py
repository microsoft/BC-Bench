import importlib
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import yaml

from bcbench.agent.shared.mcp import build_mcp_config
from bcbench.agent.shared.prompt import build_prompt
from bcbench.config import get_config
from bcbench.dataset import TestGenEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.results.base import BaseEvaluationResult, ExecutionBasedEvaluationResult
from bcbench.results.bceval_export import write_bceval_results
from bcbench.results.bugfix import BugFixResult
from bcbench.results.investigation import InvestigatedExecutionResult, InvestigationMeasurement, InvestigationSummary
from bcbench.results.leaderboard import ExecutionBasedLeaderboardAggregate, LeaderboardAggregate
from bcbench.results.summary import EvaluationResultSummary, ExecutionBasedEvaluationResultSummary
from bcbench.results.testgeneration import TestGenerationResult
from bcbench.types import AgentMetrics, EvaluationCategory, ExperimentConfiguration, HistoryQuery, HistorySettings, InvestigationTrace, ScopeSnapshot
from tests.conftest import create_dataset_entry, create_evaluation_context, create_nl2al_entry


def _patch(*paths):
    return "".join(f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n" for path in paths)


@pytest.fixture
def history_config():
    config_path = get_config().paths.agent_share_dir / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["history"] = {"enabled": True, "max_commits": 3, "max_files": 10, "history_depth": 200, "max_requests": 2}
    config["mcp"] = {"servers": []}
    return config


@pytest.fixture
def trace():
    return InvestigationTrace(
        initial_scope=ScopeSnapshot(files=[r"SRC\A.AL"], note="Initial source finding"),
        final_scope=ScopeSnapshot(files=["src/A.al", "src/B.al", "src/Extra.al"], note="B is related; Extra needs inspection"),
        queries=[
            HistoryQuery(files=["src/A.al"], elapsed_seconds=2.5, commit_ids=["b" * 40], report_name="history-001.md"),
            HistoryQuery(files=["missing.al"], elapsed_seconds=0.5, error="File unavailable before cutoff"),
        ],
    )


@pytest.mark.parametrize("category", [EvaluationCategory.BUG_FIX, EvaluationCategory.TEST_GENERATION])
def test_prompt_adds_scope_then_history_without_prefilling_gold_paths(tmp_path, history_config, category):
    entry = create_dataset_entry(patch=_patch("GOLD_ONLY.al"))
    settings = HistorySettings(enabled=True, measure_scope=True)
    with patch.object(type(entry), "get_task", return_value="Investigate the issue"):
        prompt = build_prompt(entry, tmp_path, history_config, category, history=settings)
    assert 'stage="initial"' in prompt
    assert "Then call get_history" in prompt
    assert 'stage="final"' in prompt
    assert prompt.index('stage="initial"') < prompt.index("Then call get_history")
    assert "GOLD_ONLY.al" not in prompt
    assert entry.base_commit not in prompt
    assert "Co-occurrence in a commit is a lead" in prompt


def test_measurement_only_prompt_is_an_explicit_source_only_control(tmp_path, history_config):
    entry = create_dataset_entry()
    with patch.object(type(entry), "get_task", return_value="Investigate"):
        prompt = build_prompt(entry, tmp_path, history_config, EvaluationCategory.BUG_FIX, history=HistorySettings(measure_scope=True))
    assert "source-only control" in prompt
    assert 'stage="initial"' in prompt
    assert 'stage="final"' in prompt
    assert "Then call get_history" not in prompt


def test_default_prompt_and_unrelated_categories_do_not_get_history_step(tmp_path, history_config):
    entry = create_nl2al_entry()
    history_config["prompt"]["nl2al-template"] = "Task: {{task}}"
    baseline = build_prompt(entry, tmp_path, history_config, EvaluationCategory.NL2AL)
    enabled = build_prompt(entry, tmp_path, history_config, EvaluationCategory.NL2AL, history=HistorySettings(enabled=True, measure_scope=True))
    assert enabled == baseline
    bug = create_dataset_entry()
    with patch.object(type(bug), "get_task", return_value="Task"):
        default = build_prompt(bug, tmp_path, history_config, EvaluationCategory.BUG_FIX)
        disabled = build_prompt(bug, tmp_path, history_config, EvaluationCategory.BUG_FIX, history=HistorySettings())
    assert disabled == default
    assert "record_scope" not in default


def test_missing_investigation_prompt_fails_explicitly(tmp_path):
    entry = create_dataset_entry()
    with patch.object(type(entry), "get_task", return_value="Task"), pytest.raises(AgentError, match="investigation-template"):
        build_prompt(entry, tmp_path, {"prompt": {"bug-fix-template": "{{task}}"}}, EvaluationCategory.BUG_FIX, history=HistorySettings(enabled=True))


def test_mcp_registration_only_exposes_gateway_url_and_preserves_config(tmp_path):
    config = {"mcp": {"servers": [{"name": "other", "type": "http", "url": "http://localhost:1234/mcp"}]}}
    original = json.dumps(config, sort_keys=True)
    encoded, names = build_mcp_config(config, create_dataset_entry(), tmp_path, history_gateway_url="http://127.0.0.1:5678/pinned")
    assert names == ["other", "history"]
    assert encoded is not None
    server = json.loads(encoded)["mcpServers"]["history"]
    assert server == {"type": "http", "url": "http://127.0.0.1:5678/pinned/mcp"}
    assert json.dumps(config, sort_keys=True) == original
    assert "commit" not in encoded
    assert "patch" not in encoded
    assert "Authorization" not in encoded


@pytest.mark.parametrize("harness", ["copilot", "claude"])
@pytest.mark.parametrize("outcome", ["success", "timeout", "error"])
def test_agent_wires_pinned_gateway_records_trace_and_cleans_up(harness, outcome, tmp_path, history_config, trace, monkeypatch):
    module = importlib.import_module(f"bcbench.agent.{harness}.agent")
    gateway = SimpleNamespace(base_url="http://127.0.0.1:1234/pinned", trace=trace, stop=Mock())
    start = Mock(return_value=gateway)
    monkeypatch.setattr(module.yaml, "safe_load", lambda _: history_config)
    monkeypatch.setattr(module, "build_prompt", Mock(return_value="Task"))
    monkeypatch.setattr(module, "start_history_gateway", start)
    monkeypatch.setattr(module, "start_bc_mcp_gateway", lambda _: None)
    monkeypatch.setattr(module, "build_al_lsp_plugin", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "setup_instructions_from_config", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "setup_agent_skills", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "setup_custom_agent", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "resolve_config_plugins", lambda *args, **kwargs: [])
    raw_metrics = AgentMetrics(execution_time=1.0)
    error = None
    if outcome == "timeout":
        error = subprocess.TimeoutExpired("agent", 1)
    elif outcome == "error":
        error = subprocess.CalledProcessError(1, "agent", stderr="agent failed")

    if harness == "copilot":
        invocation = Mock(return_value=(raw_metrics, ""), side_effect=error)
        monkeypatch.setattr(module, "invoke_copilot", invocation)
        run = module.run_copilot_agent
    else:
        invocation = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=b"{}\n", stderr=b""), side_effect=error)
        monkeypatch.setattr(module.shutil, "which", lambda _: "claude")
        monkeypatch.setattr(module.subprocess, "run", invocation)
        monkeypatch.setattr(module, "parse_stream_output", lambda *args, **kwargs: (raw_metrics, ""))
        run = module.run_claude_code
    entry = create_dataset_entry()
    arguments = {"entry": entry, "model": "test-model", "category": EvaluationCategory.BUG_FIX, "repo_path": tmp_path, "output_dir": tmp_path}

    if outcome == "success":
        metrics, experiment = run(**arguments)
        assert metrics.investigation == trace
        assert experiment.history.enabled
        assert experiment.history.measure_scope
        assert experiment.mcp_servers == ["history"]
        assert raw_metrics.investigation is None
    else:
        with pytest.raises(AgentTimeoutError if outcome == "timeout" else AgentError) as raised:
            run(**arguments)
        if outcome == "timeout":
            assert isinstance(raised.value, AgentTimeoutError)
            assert raised.value.metrics is not None
            assert raised.value.config is not None
            assert raised.value.config.history is not None
            assert raised.value.metrics.investigation == trace
            assert raised.value.config.history.enabled
    gateway.stop.assert_called_once()
    assert start.call_args.args[0] is entry
    assert start.call_args.args[1].enabled
    assert module.build_prompt.call_args.kwargs["history"].measure_scope


@pytest.mark.parametrize(("category", "result_type"), [(EvaluationCategory.BUG_FIX, BugFixResult), (EvaluationCategory.TEST_GENERATION, TestGenerationResult)])
def test_scope_measurements_flow_to_results_and_preserve_pass_fail(category, result_type, trace, tmp_path):
    base_entry = create_dataset_entry(patch=_patch("src/A.al", "src/B.al"), test_patch=_patch("tests/Gold.al"))
    entry = TestGenEntry.model_validate(base_entry.model_dump()) if category == EvaluationCategory.TEST_GENERATION else base_entry
    context = create_evaluation_context(tmp_path, entry=entry, category=category)
    context.metrics = AgentMetrics(execution_time=1.0, investigation=trace)
    output = _patch("src/A.al", "src/Extra.al") if category == EvaluationCategory.BUG_FIX else _patch("tests/New.al")
    result = result_type.create_success(context, output)

    assert result.resolved
    assert result.build
    measurement = result.investigation
    assert measurement is not None
    assert measurement.scope_complete
    assert measurement.initial_reference_recall == 0.5
    assert measurement.final_reference_recall == 1.0
    assert measurement.reference_recall_gain == 0.5
    assert measurement.new_reference_files == ["src/B.al"]
    assert measurement.added_scope_files == ["src/B.al", "src/Extra.al"]
    assert measurement.modified_outside_reference == (["src/Extra.al"] if category == EvaluationCategory.BUG_FIX else ["tests/New.al"])
    assert result.category_metrics["history_queries"] == 2
    assert result.category_metrics["history_errors"] == 1
    assert result.category_metrics["history_seconds"] == 3.0
    assert result.category_metrics["scope_reference_source_files"] == 2
    assert result.category_metrics["scope_reference_recall_gain"] == 0.5
    loaded = BaseEvaluationResult.from_json(result.model_dump(mode="json"))
    assert isinstance(loaded, InvestigatedExecutionResult)
    assert loaded.investigation == measurement
    assert "investigation" not in result.metrics.model_dump()
    assert "History Queries" in result.display_row


def test_missing_scope_is_not_scored_as_zero_and_timeout_retains_trace(tmp_path, caplog):
    context = create_evaluation_context(tmp_path, entry=create_dataset_entry(patch=_patch("src/A.al")))
    context.metrics = AgentMetrics(execution_time=1.0, investigation=InvestigationTrace(initial_scope=ScopeSnapshot(files=["src/A.al"])))
    result = BugFixResult.create_agent_timeout_failure(context)
    assert result.timeout
    assert result.investigation is not None
    assert result.investigation.initial_reference_recall == 1.0
    assert result.investigation.final_reference_recall is None
    assert result.investigation.reference_recall_gain is None
    assert result.investigation.modified_files is None
    assert "scope_reference_recall_final" not in result.category_metrics
    assert "incomplete" in caplog.text


def test_disabled_and_other_category_result_payloads_stay_unchanged(tmp_path):
    context = create_evaluation_context(tmp_path)
    context.metrics = AgentMetrics(execution_time=1.0)
    result = BugFixResult.create_success(context, _patch("src/A.al"))
    assert "investigation" not in result.model_dump()
    assert "history" not in ExperimentConfiguration().model_dump()
    assert "investigation" not in AgentMetrics().model_dump()
    context.category = EvaluationCategory.DATA_QUERY
    data_result = ExecutionBasedEvaluationResult.create_success(context, "rows")
    assert data_result.category_metrics == {"resolved": True, "build": True}
    summary = EvaluationResultSummary.from_results([data_result], "run")
    assert "investigation" not in summary.model_dump()


def test_scope_summary_uses_complete_pairs_and_combines_denominators(trace):
    complete = InvestigationMeasurement(trace=trace, reference_source_files=["src/A.al", "src/B.al"], reference_output_files=["src/A.al"], modified_files=["src/A.al"])
    incomplete = complete.model_copy(update={"trace": InvestigationTrace(initial_scope=ScopeSnapshot(files=["src/A.al"]))})
    summary = InvestigationSummary.from_measurements([complete, incomplete])
    assert summary is not None
    assert summary.attempts == 2
    assert summary.complete_scope_attempts == 1
    assert summary.paired_reference_attempts == 1
    assert summary.average_initial_reference_recall == 0.5
    assert summary.average_final_reference_recall == 1.0
    assert summary.average_reference_recall_gain == 0.5
    assert summary.history_used_attempts == summary.history_returned_attempts == 1
    single = InvestigationSummary.from_measurements([complete])
    assert single is not None
    combined = InvestigationSummary.combine([summary, single])
    assert combined is not None
    assert combined.attempts == 3
    assert combined.paired_reference_attempts == 2
    assert combined.average_reference_recall_gain == 0.5


def test_measurements_are_summarized_exportable_and_separate_experiment_arms(tmp_path, trace):
    context = create_evaluation_context(tmp_path, entry=create_dataset_entry(patch=_patch("src/A.al", "src/B.al")))
    context.metrics = AgentMetrics(execution_time=1.0, investigation=trace)
    context.experiment = ExperimentConfiguration(history=HistorySettings(enabled=True, measure_scope=True))
    result = BugFixResult.create_success(context, _patch("src/A.al"))
    summary = EvaluationResultSummary.from_results([result], "run")
    assert isinstance(summary, ExecutionBasedEvaluationResultSummary)
    assert summary.investigation is not None
    assert summary.investigation.average_reference_recall_gain == 0.5
    assert "agent-reported file scope" in summary.render_github_metrics_markdown()
    assert summary.render_console_metrics() is not None
    aggregate = LeaderboardAggregate.from_runs([summary])
    assert isinstance(aggregate, ExecutionBasedLeaderboardAggregate)
    assert aggregate.investigation is not None
    assert aggregate.investigation.attempts == 1
    assert aggregate.average == 1.0
    control = summary.model_copy(update={"experiment": ExperimentConfiguration(history=HistorySettings(measure_scope=True))})
    assert control.combination_key() != summary.combination_key()
    assert control.experiment is not None
    assert not control.experiment.is_empty()

    with patch.object(type(context.entry), "load", return_value=[context.entry]), patch.object(type(context.entry), "get_task", return_value="Issue"):
        write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.BUG_FIX)
    exported = json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))
    assert exported["metadata"]["scope_reference_recall_gain"] == 0.5
    assert exported["metadata"]["history_queries"] == 2
    assert exported["metadata"]["resolved"] is True
    assert exported["metadata"]["experiment"]["history"]["enabled"] is True
