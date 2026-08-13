import json
from pathlib import Path

from bcbench.results.codereview import CodeReviewResultSummary
from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate, ExecutionBasedLeaderboardAggregate
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary
from bcbench.types import AgentMetrics
from tests.conftest import create_bugfix_result, create_codereview_result


def _metrics(tokens: int, calls: int, credits: float, used: int, pruned: int) -> AgentMetrics:
    return AgentMetrics(
        execution_time=4.0,
        prompt_tokens=tokens - 100,
        completion_tokens=100,
        total_tokens=tokens,
        api_calls=calls,
        estimated_credits=credits,
        knowledge_used=used,
        knowledge_pruned=pruned,
    )


def test_summary_aggregates_pr_review_metrics() -> None:
    summary = CodeReviewResultSummary.from_results(
        [
            create_codereview_result(instance_id="proj__review-1", metrics=_metrics(1000, 10, 0.5, 20, 4)),
            create_codereview_result(instance_id="proj__review-2", metrics=_metrics(2000, 20, 1.5, 30, 8)),
        ],
        run_id="run",
    )

    assert summary.average_total_tokens == 1500
    assert summary.average_api_calls == 15
    assert summary.average_estimated_credits == 1
    assert summary.average_knowledge_used == 25
    assert summary.average_knowledge_pruned == 6


def test_leaderboard_propagates_pr_review_metrics() -> None:
    first = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=_metrics(1000, 10, 0.5, 20, 4))],
        run_id="one",
    )
    second = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=_metrics(2000, 20, 1.5, 30, 8))],
        run_id="two",
    )

    aggregate = CodeReviewLeaderboardAggregate.from_runs([first, second])

    assert aggregate.average_total_tokens == 1500
    assert aggregate.average_knowledge_used == 25
    assert aggregate.average_knowledge_pruned == 6


def test_github_summary_renders_performance_metrics() -> None:
    summary = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=_metrics(1500, 12, 0.75, 24, 5))],
        run_id="run",
    )

    markdown = summary.render_github_metrics_markdown()

    assert "## Performance" in markdown
    assert "Avg knowledge used" in markdown
    assert "0.7500" in markdown


def test_github_summary_renders_knowledge_only_metrics() -> None:
    metrics = AgentMetrics(execution_time=4.0, knowledge_used=24, knowledge_pruned=5)
    summary = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=metrics)],
        run_id="run",
    )

    markdown = summary.render_github_metrics_markdown()

    assert "## Performance" in markdown
    assert "| 4.0 | n/a | n/a | n/a | 24.0 | 5.0 |" in markdown


def test_execution_based_models_do_not_serialize_code_review_metrics(tmp_path: Path) -> None:
    result = create_bugfix_result(metrics=AgentMetrics(execution_time=4.0))
    summary = ExecutionBasedEvaluationResultSummary.from_results([result], run_id="run")
    aggregate = ExecutionBasedLeaderboardAggregate.from_runs([summary])
    result.save(tmp_path, "results.jsonl")
    saved_result = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8"))

    assert "total_tokens" not in saved_result["metrics"]
    assert "knowledge_used" not in saved_result["metrics"]
    assert "average_total_tokens" not in summary.to_dict()
    assert "average_knowledge_used" not in summary.to_dict()
    assert "average_total_tokens" not in aggregate.model_dump(mode="json")
    assert "average_knowledge_used" not in aggregate.model_dump(mode="json")
