from unittest.mock import MagicMock, call, patch

import pytest
from bcbench_core.agent.experiment import ExperimentConfiguration
from bcbench_core.agent.harness import AgentResult
from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.evaluation import evaluate_task
from bcbench_core.exceptions import AgentError, AgentTimeoutError, EmptyDiffError

from bcbench.categories.data_query import ANSWER_FILE, GENERATED_QUERY_FILE, DataQueryCategory, DataQueryEntry
from bcbench.categories.ext_request_implement import ExtRequestImplementCategory, ExtRequestImplementEntry
from bcbench.categories.ext_request_triage import TRIAGE_RESULT_FILE, ExtRequestTriageCategory, ExtRequestTriageEntry
from bcbench.commands import evaluate as evaluate_commands
from bcbench.commands import run as run_commands
from bcbench.dataset import BaseDatasetEntry
from bcbench.results.base import RESULT_FILE_SUFFIX, BaseEvaluationResult, ExecutionBasedEvaluationResult, JudgeBasedEvaluationResult
from bcbench.results.leaderboard import ExecutionBasedLeaderboardAggregate, JudgeBasedLeaderboardAggregate
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary, JudgeBasedEvaluationResultSummary
from bcbench.types import AgentConfig, DatasetTier, EvaluationCategory
from tests.conftest import StubHarness, create_data_query_entry, create_evaluation_context, create_ext_implement_entry, create_ext_triage_entry

MIGRATED_CATEGORIES = (
    EvaluationCategory.EXT_REQUEST_IMPLEMENT,
    EvaluationCategory.EXT_REQUEST_TRIAGE,
    EvaluationCategory.DATA_QUERY,
)


@pytest.fixture(params=MIGRATED_CATEGORIES)
def category_context(request, tmp_path, monkeypatch):
    category = request.param
    entry: BaseDatasetEntry
    match category:
        case EvaluationCategory.EXT_REQUEST_IMPLEMENT:
            entry = create_ext_implement_entry()
            monkeypatch.setattr("bcbench.categories.ext_request_implement.stage_and_get_diff", lambda *_args, **_kwargs: "generated patch")
        case EvaluationCategory.EXT_REQUEST_TRIAGE:
            entry = create_ext_triage_entry()
        case EvaluationCategory.DATA_QUERY:
            entry = create_data_query_entry()
            monkeypatch.setattr("bcbench.operations.execute_al_query", lambda *_args, **_kwargs: [{"Total": 42}])
        case _:
            raise AssertionError(f"Unexpected category: {category}")
    context = create_evaluation_context(tmp_path, entry=entry, category=category)
    context.repo_path.mkdir()
    (context.repo_path / TRIAGE_RESULT_FILE).write_text('{"issue_state":"open"}', encoding="utf-8")
    (context.repo_path / ANSWER_FILE).write_text('[{"Total":42}]', encoding="utf-8")
    (context.repo_path / GENERATED_QUERY_FILE).write_text("generated query", encoding="utf-8")
    return context


@pytest.mark.parametrize(
    ("category", "entry_type", "implementation_type", "filename"),
    [
        (EvaluationCategory.EXT_REQUEST_IMPLEMENT, ExtRequestImplementEntry, ExtRequestImplementCategory, "extensibility_request_implement.jsonl"),
        (EvaluationCategory.EXT_REQUEST_TRIAGE, ExtRequestTriageEntry, ExtRequestTriageCategory, "extensibility_request_triage.jsonl"),
        (EvaluationCategory.DATA_QUERY, DataQueryEntry, DataQueryCategory, "dataquery.jsonl"),
    ],
)
def test_category_definition_preserves_metadata(category, entry_type, implementation_type, filename):
    definition = category.definition
    assert definition is not None
    assert definition.category is category
    assert category.entry_class is entry_type
    assert isinstance(definition.make(AgentConfig()), implementation_type)
    assert category.dataset_path().name == filename
    assert entry_type.load(category.dataset_path())
    with pytest.raises(ValueError, match="has no challenge dataset"):
        category.dataset_path(DatasetTier.CHALLENGE)
    with pytest.raises(ValueError, match="evaluated through its category definition"):
        category.pipeline(AgentConfig())

    execution_based = category is EvaluationCategory.DATA_QUERY
    assert category.result_class is (ExecutionBasedEvaluationResult if execution_based else JudgeBasedEvaluationResult)
    assert category.summary_class is (ExecutionBasedEvaluationResultSummary if execution_based else JudgeBasedEvaluationResultSummary)
    assert category.aggregate_class is (ExecutionBasedLeaderboardAggregate if execution_based else JudgeBasedLeaderboardAggregate)
    assert category.evaluators == (["resolution_rate", "build_rate"] if execution_based else ["lm_checklist"])
    assert category.core_score == ("ResolutionRate" if execution_based else "test_passed")
    assert definition.judge == (None if execution_based else "lm-checklist")
    assert category.requires_container is execution_based
    assert category.requires_repo is not execution_based
    assert category.pass_on_bc_container_credentials is not execution_based
    assert category.runner == ("GitHub-BCBench" if execution_based else "ubuntu-latest")


def test_evaluate_task_returns_category_result_without_saving(category_context):
    context = category_context
    definition = context.category.definition
    assert definition is not None
    implementation = definition.make(AgentConfig())
    observed = AgentResult(
        metrics=AgentMetrics(execution_time=1.0),
        experiment=ExperimentConfiguration(custom_instructions=True),
        transcript={"trace": ["agent output"]},
    )
    harness = StubHarness(observed)

    with patch.object(type(implementation), "prepare") as prepare:
        result = evaluate_task(implementation, context, harness, context.agent_request(), on_timeout=definition.timeout_result)

    prepare.assert_called_once_with(context)
    assert harness.requests == [context.agent_request()]
    assert isinstance(result, definition.result_type)
    assert result.category is context.category
    assert result.metrics == observed.metrics
    assert result.experiment == observed.experiment
    assert result.transcript == observed.transcript
    assert not result.timeout
    if isinstance(result, ExecutionBasedEvaluationResult):
        assert result.build
        assert result.resolved
        assert result.output == "generated query"
    else:
        assert isinstance(result, JudgeBasedEvaluationResult)
        assert result.judge_model == context.category.judge_model
        assert result.output == ('{"issue_state":"open"}' if context.category is EvaluationCategory.EXT_REQUEST_TRIAGE else "generated patch")
    assert not context.result_dir.exists()


def test_timeout_skips_grading_and_keeps_observed_metadata(category_context):
    context = category_context
    definition = context.category.definition
    assert definition is not None
    implementation = definition.make(AgentConfig())
    harness = MagicMock(spec=StubHarness)
    timeout = AgentTimeoutError("timeout", metrics=AgentMetrics(execution_time=600), config=ExperimentConfiguration(custom_instructions=True), transcript={"trace": []})
    harness.run.side_effect = timeout

    with patch.object(type(implementation), "prepare"), patch.object(type(implementation), "grade") as grade:
        result = evaluate_task(implementation, context, harness, context.agent_request(), on_timeout=definition.timeout_result)

    grade.assert_not_called()
    assert isinstance(result, definition.result_type)
    assert result.timeout
    assert result.error_message == "Agent timed out"
    assert result.agent_version == context.agent.version
    assert result.metrics == timeout.metrics
    assert result.experiment == timeout.config
    assert result.transcript == timeout.transcript
    if isinstance(result, JudgeBasedEvaluationResult):
        assert result.judge_model == context.category.judge_model
    else:
        assert isinstance(result, ExecutionBasedEvaluationResult)
        assert not result.build
        assert not result.resolved


def test_agent_error_propagates_without_grading(category_context):
    context = category_context
    definition = context.category.definition
    assert definition is not None
    implementation = definition.make(AgentConfig())
    harness = MagicMock(spec=StubHarness)
    harness.run.side_effect = AgentError("agent failed")

    with patch.object(type(implementation), "prepare"), patch.object(type(implementation), "grade") as grade, pytest.raises(AgentError, match="agent failed"):
        evaluate_task(implementation, context, harness, context.agent_request(), on_timeout=definition.timeout_result)

    grade.assert_not_called()


@pytest.mark.parametrize("harness_name", ["CopilotHarness", "ClaudeHarness"])
def test_run_commands_use_category_workspace(category_context, harness_name):
    context = category_context
    definition = context.category.definition
    assert definition is not None
    implementation_type = type(definition.make(AgentConfig()))
    command = run_commands.run_copilot if harness_name == "CopilotHarness" else run_commands.run_claude
    harness = StubHarness()
    with (
        patch.object(context.category.entry_class, "load", return_value=[context.entry]),
        patch.object(implementation_type, "prepare_workspace") as prepare_workspace,
        patch.object(implementation_type, "prepare") as prepare,
        patch.object(run_commands, harness_name, return_value=harness),
    ):
        command(context.entry.instance_id, context.category, repo_path=context.repo_path, output_dir=context.result_dir)

    prepare_workspace.assert_called_once()
    prepare.assert_not_called()
    assert prepare_workspace.call_args.args[0].entry is context.entry
    assert harness.requests[0].task is context.entry
    assert harness.requests[0].work_dir == context.repo_path


@pytest.mark.parametrize("harness_name", ["CopilotHarness", "ClaudeHarness"])
def test_evaluate_commands_save_category_result(category_context, harness_name):
    context = category_context
    definition = context.category.definition
    assert definition is not None
    implementation_type = type(definition.make(AgentConfig()))
    command = evaluate_commands.evaluate_copilot if harness_name == "CopilotHarness" else evaluate_commands.evaluate_claude_code
    with (
        patch.object(context.category.entry_class, "load", return_value=[context.entry]),
        patch.object(implementation_type, "prepare"),
        patch.object(evaluate_commands, harness_name, return_value=StubHarness()),
        patch.object(evaluate_commands, "resolve_evaluation_runtime", return_value=None),
        patch.object(DataQueryCategory, "_gold_rows", return_value=[{"Total": 42}]),
    ):
        command(context.entry.instance_id, context.category, repo_path=context.repo_path, output_dir=context.result_dir, run_id="run")

    result_file = context.result_dir / "run" / f"{context.entry.instance_id}{RESULT_FILE_SUFFIX}"
    lines = result_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    restored = BaseEvaluationResult.from_json(definition.result_type.model_validate_json(lines[0]).model_dump())
    assert isinstance(restored, definition.result_type)
    assert restored.category is context.category
    assert restored.output


@pytest.mark.parametrize("method", ["prepare_workspace", "prepare"])
def test_implement_preparation_preserves_setup_order(tmp_path, method):
    context = create_evaluation_context(tmp_path, entry=create_ext_implement_entry(), category=EvaluationCategory.EXT_REQUEST_IMPLEMENT)
    with (
        patch("bcbench.categories.ext_request_implement.setup_repo_prebuild") as setup_repo,
        patch("bcbench.categories.ext_request_implement.copy_problem_statement_folder") as copy_problem,
        patch("bcbench.categories.ext_request_implement.set_runtime_version") as set_runtime,
    ):
        calls = MagicMock()
        calls.attach_mock(setup_repo, "setup_repo")
        calls.attach_mock(copy_problem, "copy_problem")
        calls.attach_mock(set_runtime, "set_runtime")
        getattr(ExtRequestImplementCategory(), method)(context)

    assert calls.mock_calls == [
        call.setup_repo(context.entry, context.repo_path),
        call.copy_problem(context.entry, context.repo_path),
        call.set_runtime(context.repo_path, context.entry.project_paths),
    ]


def test_implement_empty_diff_returns_empty_output(tmp_path):
    context = create_evaluation_context(tmp_path, entry=create_ext_implement_entry(), category=EvaluationCategory.EXT_REQUEST_IMPLEMENT)
    with patch("bcbench.categories.ext_request_implement.stage_and_get_diff", side_effect=EmptyDiffError()):
        result = ExtRequestImplementCategory().grade(context, AgentResult())

    assert result.output == ""
    assert result.error_message is None


@pytest.mark.parametrize("method", ["prepare_workspace", "prepare"])
def test_triage_preparation_removes_stale_output(tmp_path, method):
    context = create_evaluation_context(tmp_path, entry=create_ext_triage_entry(), category=EvaluationCategory.EXT_REQUEST_TRIAGE)
    context.repo_path.mkdir()
    result_file = context.repo_path / TRIAGE_RESULT_FILE
    result_file.write_text("stale", encoding="utf-8")
    with patch("bcbench.categories.ext_request_triage.setup_repo_prebuild") as setup_repo:
        getattr(ExtRequestTriageCategory(), method)(context)

    setup_repo.assert_called_once_with(context.entry, context.repo_path)
    assert not result_file.exists()


@pytest.mark.parametrize("content", [None, "", " \n", "unvalidated raw decision\n"])
def test_triage_keeps_raw_output_or_empty_output(tmp_path, content):
    context = create_evaluation_context(tmp_path, entry=create_ext_triage_entry(), category=EvaluationCategory.EXT_REQUEST_TRIAGE)
    context.repo_path.mkdir()
    if content is not None:
        (context.repo_path / TRIAGE_RESULT_FILE).write_text(content, encoding="utf-8")

    result = ExtRequestTriageCategory().grade(context, AgentResult())

    assert result.output == (content.strip() if content else "")
    assert result.error_message is None
