import json
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from bcbench.commands.result import _rebuild_aggregates, result_update
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.exceptions import AgentTimeoutError
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate, Leaderboard
from bcbench.results.summary import EvaluationResultSummary
from bcbench.types import AgentHarness, EvaluationCategory, EvaluationContext, ExperimentConfiguration, PRReviewConfiguration, PRReviewMetrics
from tests.conftest import create_codereview_entry, create_codereview_result


def _configuration(
    *,
    leaf_model: str = "gpt-5.6-luna",
    leaf_execution: Literal["serial", "parallel"] = "serial",
    max_leaf_concurrency: int = 4,
    cli_version: str = "1.0.83",
) -> ExperimentConfiguration:
    return ExperimentConfiguration(
        pr_review=PRReviewConfiguration(
            leaf_model=leaf_model,
            leaf_execution=leaf_execution,
            max_leaf_concurrency=max_leaf_concurrency,
            copilot_cli_version=cli_version,
        )
    )


def _summary(config: ExperimentConfiguration | None, run_id: str = "run") -> EvaluationResultSummary:
    result = create_codereview_result(agent_name=AgentHarness.PR_REVIEW, model="gpt-5.6-sol").model_copy(update={"experiment": config, "agent_version": "e" * 40})
    return EvaluationResultSummary.from_results([result], run_id)


def test_routing_variants_have_separate_combinations_and_history(tmp_path: Path) -> None:
    configs = [
        _configuration(),
        _configuration(leaf_model="gpt-5.4"),
        _configuration(leaf_execution="parallel", max_leaf_concurrency=2),
        _configuration(leaf_execution="parallel", max_leaf_concurrency=4),
        _configuration(cli_version="1.0.88"),
        None,
    ]
    summaries = [_summary(config) for config in configs]
    assert len({summary.combination_key() for summary in summaries}) == len(configs)
    assert len(_rebuild_aggregates(summaries)) == len(configs)
    for variant in summaries[1:]:
        with pytest.raises(ValueError, match="different combinations"):
            CodeReviewLeaderboardAggregate.from_runs([summaries[0], variant])

    for repetition in range(3):
        for index, config in enumerate(configs):
            summary = _summary(config, f"{index}-{repetition}")
            summary.save(tmp_path, "summary.json")
            result_update(tmp_path / "summary.json", leaderboard_dir=tmp_path, n=2)

    leaderboard = Leaderboard.load(tmp_path / "code-review.json")
    assert len(leaderboard.runs) == 2 * len(configs)
    assert len(leaderboard.aggregate) == len(configs)
    assert all(aggregate.num_runs == 2 for aggregate in leaderboard.aggregate)
    assert {run.github_run_id for run in leaderboard.runs} == {f"{index}-{repetition}" for index in range(len(configs)) for repetition in (1, 2)}
    for original in summaries:
        restored = next(run for run in leaderboard.runs if run.combination_key() == original.combination_key())
        assert restored.experiment == original.experiment


def test_serial_concurrency_is_not_part_of_identity() -> None:
    first = _summary(_configuration(max_leaf_concurrency=1))
    second = _summary(_configuration(max_leaf_concurrency=99))

    assert first.experiment is not None
    assert first.experiment.pr_review is not None
    assert first.experiment.pr_review.max_leaf_concurrency is None
    assert first.combination_key() == second.combination_key()
    assert CodeReviewLeaderboardAggregate.from_runs([first, second]).num_runs == 2
    assert not first.experiment.is_empty()


@pytest.mark.parametrize(
    "config",
    [
        _configuration(leaf_model="gpt-5.4"),
        _configuration(leaf_execution="parallel"),
        _configuration(cli_version="1.0.88"),
        None,
    ],
)
def test_summary_rejects_mixed_entry_identities(config: ExperimentConfiguration | None) -> None:
    result = create_codereview_result(agent_name=AgentHarness.PR_REVIEW)
    first = result.model_copy(update={"experiment": _configuration()})
    second = result.model_copy(update={"experiment": config})

    with pytest.raises(ValueError, match="different experiment configurations"):
        EvaluationResultSummary.from_results([first, second], "mixed")


def test_old_experiment_payload_remains_readable() -> None:
    summary = _summary(ExperimentConfiguration(custom_instructions=True))
    payload = summary.to_dict()
    del payload["experiment"]["pr_review"]

    assert EvaluationResultSummary.from_json(payload).combination_key() == summary.combination_key()


def test_parallel_configuration_requires_concurrency() -> None:
    with pytest.raises(ValidationError, match="requires max_leaf_concurrency"):
        PRReviewConfiguration(leaf_model="gpt-5.6-luna", leaf_execution="parallel", copilot_cli_version="1.0.83")


@pytest.mark.parametrize("outcome", ["completed", "invalid", "timeout"])
def test_pipeline_persists_identity_for_every_result_outcome(tmp_path: Path, outcome: str) -> None:
    config = _configuration(leaf_execution="parallel", max_leaf_concurrency=2)
    context = EvaluationContext(
        entry=create_codereview_entry(),
        repo_path=tmp_path,
        result_dir=tmp_path,
        container=None,
        agent_name=AgentHarness.PR_REVIEW,
        agent_version="e" * 40,
        model="gpt-5.6-sol",
        category=EvaluationCategory.CODE_REVIEW,
    )
    metrics = PRReviewMetrics(execution_time=1.0)
    (tmp_path / "review.json").write_text("invalid" if outcome == "invalid" else "[]", encoding="utf-8")

    def run(_):
        if outcome == "timeout":
            raise AgentTimeoutError("timeout", metrics=metrics, config=config)
        return metrics, config

    pipeline = CodeReviewPipeline()
    with (
        patch.object(CodeReviewPipeline, "setup"),
        patch("bcbench.evaluate.codereview.judge_expected_and_ignored", return_value=([], [])),
    ):
        pipeline.execute(context, run)

    result_path = next(tmp_path.glob("*.jsonl"))
    restored = BaseEvaluationResult.from_json(json.loads(result_path.read_text(encoding="utf-8")))
    summary = EvaluationResultSummary.from_results([restored], "run")
    assert restored.experiment == summary.experiment == config
    assert restored.timeout is (outcome == "timeout")
    assert summary.combination_key() == _summary(config).combination_key()
