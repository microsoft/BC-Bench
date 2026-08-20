import json
from pathlib import Path

from bcbench.results.codereview import CodeReviewResultSummary
from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate
from bcbench.types import AgentMetrics
from tests.conftest import create_bugfix_result, create_codereview_result


def _metrics(duration: float, available: int, pruned: int) -> AgentMetrics:
    return AgentMetrics(execution_time=duration, knowledge_files=available, knowledge_pruned=pruned)


def test_summary_aggregates_pr_review_metrics() -> None:
    summary = CodeReviewResultSummary.from_results(
        [
            create_codereview_result(instance_id="proj__review-1", metrics=_metrics(4.0, 20, 4)),
            create_codereview_result(instance_id="proj__review-2", metrics=_metrics(6.0, 30, 8)),
        ],
        run_id="run",
    )

    assert summary.average_duration == 5
    assert summary.average_knowledge_files == 25
    assert summary.average_knowledge_pruned == 6


def test_leaderboard_propagates_pr_review_metrics() -> None:
    first = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=_metrics(4.0, 20, 4))],
        run_id="one",
    )
    second = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=_metrics(6.0, 30, 8))],
        run_id="two",
    )

    aggregate = CodeReviewLeaderboardAggregate.from_runs([first, second])

    assert aggregate.average_duration == 5
    assert aggregate.average_knowledge_files == 25
    assert aggregate.average_knowledge_pruned == 6


def test_github_summary_renders_performance_metrics() -> None:
    summary = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=_metrics(4.0, 24, 5))],
        run_id="run",
    )

    markdown = summary.render_github_metrics_markdown()

    assert "## Performance" in markdown
    assert "Avg knowledge files" in markdown
    assert "| 4.0 | 24.0 | 5.0 |" in markdown


def test_generic_result_does_not_serialize_pr_review_metrics(tmp_path: Path) -> None:
    result = create_bugfix_result(metrics=AgentMetrics(execution_time=4.0))
    result.save(tmp_path, "results.jsonl")

    saved_result = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8"))

    assert "knowledge_files" not in saved_result["metrics"]
    assert "knowledge_pruned" not in saved_result["metrics"]


def test_code_review_result_serializes_pr_review_metrics(tmp_path: Path) -> None:
    result = create_codereview_result(metrics=_metrics(4.0, 24, 5))
    result.save(tmp_path, "results.jsonl")

    saved_result = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8"))

    assert saved_result["metrics"]["knowledge_files"] == 24
    assert saved_result["metrics"]["knowledge_pruned"] == 5
