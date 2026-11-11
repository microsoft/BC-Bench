import json
from pathlib import Path
from unittest.mock import patch

import pytest
from bcbench_core.agent.experiment import ExperimentConfiguration
from bcbench_core.agent.harness import AgentResult
from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.exceptions import AgentTimeoutError

from bcbench.commands.result import _rebuild_aggregates, result_update
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.bugfix import BugFixResult
from bcbench.results.leaderboard import Leaderboard, LeaderboardAggregate
from bcbench.results.summary import EvaluationResultSummary
from bcbench.types import AgentConfig, EvaluationCategory, HarnessName
from tests.conftest import StubHarness, create_bugfix_result, create_codereview_result, create_evaluation_context


@pytest.mark.parametrize("version", ["1.2.3", "a" * 40, None])
def test_agent_version_round_trips_through_results_and_summaries(tmp_path: Path, version: str | None) -> None:
    result = BugFixResult.create_success(create_evaluation_context(tmp_path), AgentResult(), "patch").model_copy(update={"agent_version": version})
    result.save(tmp_path, "result.jsonl")
    restored = BaseEvaluationResult.from_json(json.loads((tmp_path / "result.jsonl").read_text()))
    summary = EvaluationResultSummary.from_results([restored], "run")
    aggregate = LeaderboardAggregate.from_runs([summary])

    assert restored.agent_version == summary.agent_version == aggregate.agent_version == version
    assert summary.experiment is None
    assert EvaluationResultSummary.from_json(summary.to_dict()).agent_version == version
    assert LeaderboardAggregate.from_json(aggregate.model_dump(mode="json")).agent_version == version


def test_timeout_result_keeps_version_resolved_before_execution(tmp_path: Path) -> None:
    context = create_evaluation_context(tmp_path, agent_version="1.2.3")
    pipeline = context.category.pipeline(AgentConfig())
    with (
        patch.object(type(pipeline), "setup"),
        patch.object(type(pipeline), "run_agent", side_effect=AgentTimeoutError("timeout")),
    ):
        pipeline.execute(context, StubHarness())

    saved = next(context.result_dir.glob("*.jsonl"))
    result = BaseEvaluationResult.from_json(json.loads(saved.read_text()))
    assert result.timeout is True
    assert result.agent_version == "1.2.3"


def test_summary_uses_artifact_version_not_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    result = create_bugfix_result().model_copy(update={"agent_version": "1.2.3"})
    monkeypatch.setenv("COPILOT_CLI_VERSION", "9.9.9")
    monkeypatch.setenv("BC_ALAGENTS_COMMIT", "f" * 40)

    assert EvaluationResultSummary.from_results([result], "run").agent_version == "1.2.3"


def test_repeated_versions_aggregate_and_different_versions_stay_separate(tmp_path: Path) -> None:
    for index, version in enumerate(["a" * 40, "b" * 40, "a" * 40]):
        result = create_codereview_result(agent_name=HarnessName.PR_REVIEW).model_copy(update={"agent_version": version})
        summary = EvaluationResultSummary.from_results([result], f"run-{index}")
        summary.save(tmp_path, "summary.json")
        result_update(tmp_path / "summary.json", leaderboard_dir=tmp_path, n=5)

    leaderboard = Leaderboard.load(tmp_path / f"{EvaluationCategory.CODE_REVIEW.value}.json")
    assert {aggregate.agent_version: aggregate.num_runs for aggregate in leaderboard.aggregate} == {"a" * 40: 2, "b" * 40: 1}
    assert all(aggregate.experiment is None for aggregate in leaderboard.aggregate)


@pytest.mark.parametrize("other_version", ["1.2.4", None])
def test_aggregate_rejects_different_or_unrecorded_versions(other_version: str | None) -> None:
    first = EvaluationResultSummary.from_results([create_bugfix_result().model_copy(update={"agent_version": "1.2.3"})], "run")
    second = first.model_copy(update={"agent_version": other_version})

    with pytest.raises(ValueError, match="different combinations"):
        LeaderboardAggregate.from_runs([first, second])
    assert len(_rebuild_aggregates([first, second])) == 2


def test_version_does_not_replace_existing_grouping_dimensions() -> None:
    first = EvaluationResultSummary.from_results([create_codereview_result().model_copy(update={"agent_version": "1.2.3"})], "run")
    variants = [
        first,
        first.model_copy(update={"agent_name": HarnessName.CLAUDE}),
        first.model_copy(update={"model": "different-model"}),
        first.model_copy(update={"experiment": ExperimentConfiguration(custom_instructions=True)}),
        first.model_copy(update={"benchmark_version": "different-benchmark"}),
        first.model_copy(update={"judge_model": "different-judge"}),
    ]
    assert len(_rebuild_aggregates(variants)) == len(variants)


def test_runtime_provider_and_prompt_identity_stay_separate() -> None:
    first = create_bugfix_result().model_copy(update={"agent_name": HarnessName.BCAL})
    configs = [
        {"agentRuntime": "legacy", "provider": "m365"},
        {"agentRuntime": "copilot-sdk", "provider": "m365"},
        {"agentRuntime": "copilot-sdk", "provider": "azure"},
        {"agentRuntime": "copilot-sdk", "provider": "m365", "promptHash": "different"},
    ]
    results = [first.model_copy(update={"experiment": ExperimentConfiguration(execution=config)}) for config in configs]
    summaries = [EvaluationResultSummary.from_results([result], f"run-{index}") for index, result in enumerate(results)]
    assert len(_rebuild_aggregates(summaries)) == len(configs)
    with pytest.raises(ValueError, match="mixed BCal execution identities"):
        EvaluationResultSummary.from_results(results, "mixed")


def test_missing_bcal_usage_is_unavailable_not_measured_zero() -> None:
    result = create_bugfix_result().model_copy(update={"agent_name": HarnessName.BCAL, "metrics": None})
    summary = EvaluationResultSummary.from_results([result], "run")
    assert summary.average_prompt_tokens is None
    assert summary.average_completion_tokens is None
    assert summary.average_llm_duration is None
    assert summary.usage_availability == {"runs": 1, "prompt_tokens": 0, "completion_tokens": 0, "llm_duration": 0}


def test_partial_bcal_usage_excludes_missing_runs_but_keeps_measured_zero() -> None:
    base = create_bugfix_result().model_copy(update={"agent_name": HarnessName.BCAL})
    results = [
        base.model_copy(update={"metrics": None}),
        base.model_copy(update={"metrics": AgentMetrics(prompt_tokens=0, completion_tokens=0, llm_duration=0)}),
        base.model_copy(update={"metrics": AgentMetrics(prompt_tokens=40, completion_tokens=10)}),
    ]
    summary = EvaluationResultSummary.from_results(results, "run")
    assert summary.average_prompt_tokens == 20
    assert summary.average_completion_tokens == 5
    assert summary.average_llm_duration == 0
    assert summary.usage_availability == {"runs": 3, "prompt_tokens": 2, "completion_tokens": 2, "llm_duration": 1}
    restored = EvaluationResultSummary.from_json(summary.to_dict())
    assert restored.usage_availability == summary.usage_availability
