import json
from pathlib import Path

from bcbench.results.codereview import CodeReviewResultSummary
from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate
from bcbench.types import AgentMetrics
from tests.conftest import create_bugfix_result, create_codereview_result


def _metrics(
    *,
    duration: float,
    scale: int,
    usage_complete: bool = True,
    malformed_records: int = 0,
) -> AgentMetrics:
    return AgentMetrics(
        execution_time=duration,
        prompt_tokens=900 * scale,
        cached_tokens=200 * scale,
        cache_creation_tokens=50 * scale,
        completion_tokens=100 * scale,
        reasoning_tokens=25 * scale,
        total_tokens=1000 * scale,
        api_calls=10 * scale,
        failed_api_calls=scale,
        usage_api_calls=9 * scale,
        ai_credits=0.5 * scale,
        premium_requests=0.25 * scale,
        usage_complete=usage_complete,
        malformed_records=malformed_records,
        knowledge_files=20 * scale,
        knowledge_pruned=4 * scale,
    )


def test_summary_aggregates_pr_review_metrics() -> None:
    summary = CodeReviewResultSummary.from_results(
        [
            create_codereview_result(instance_id="proj__review-1", metrics=_metrics(duration=4.0, scale=1)),
            create_codereview_result(instance_id="proj__review-2", metrics=_metrics(duration=6.0, scale=2)),
        ],
        run_id="run",
    )

    assert summary.average_duration == 5
    assert summary.average_prompt_tokens == 1350
    assert summary.average_cached_tokens == 300
    assert summary.average_cache_creation_tokens == 75
    assert summary.average_completion_tokens == 150
    assert summary.average_reasoning_tokens == 37.5
    assert summary.average_total_tokens == 1500
    assert summary.average_api_calls == 15
    assert summary.average_failed_api_calls == 1.5
    assert summary.average_usage_api_calls == 13.5
    assert summary.average_ai_credits == 0.75
    assert summary.average_premium_requests == 0.375
    assert summary.structured_usage_complete_rate == 1
    assert summary.average_malformed_records == 0
    assert summary.average_knowledge_files == 30
    assert summary.average_knowledge_pruned == 6


def test_summary_marks_malformed_structured_usage_incomplete() -> None:
    summary = CodeReviewResultSummary.from_results(
        [
            create_codereview_result(instance_id="proj__review-1", metrics=_metrics(duration=4.0, scale=1)),
            create_codereview_result(instance_id="proj__review-2", metrics=_metrics(duration=6.0, scale=2, malformed_records=2)),
        ],
        run_id="run",
    )

    assert summary.structured_usage_complete_rate == 0.5
    assert summary.average_malformed_records == 1
    assert summary.average_total_tokens == 1500


def test_summary_serializes_legal_null_token_metrics() -> None:
    metrics = AgentMetrics(
        execution_time=4.0,
        usage_complete=False,
        malformed_records=0,
        knowledge_files=20,
        knowledge_pruned=4,
    )
    summary = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=metrics)],
        run_id="run",
    )

    serialized = summary.to_dict()

    assert serialized["average_prompt_tokens"] is None
    assert serialized["average_completion_tokens"] is None
    assert serialized["structured_usage_complete_rate"] == 0


def test_leaderboard_propagates_pr_review_metrics() -> None:
    first = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=_metrics(duration=4.0, scale=1))],
        run_id="one",
    )
    second = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=_metrics(duration=6.0, scale=2, usage_complete=False))],
        run_id="two",
    )

    aggregate = CodeReviewLeaderboardAggregate.from_runs([first, second])

    assert aggregate.average_duration == 5
    assert aggregate.average_prompt_tokens == 1350
    assert aggregate.average_completion_tokens == 150
    assert aggregate.average_reasoning_tokens == 37.5
    assert aggregate.average_total_tokens == 1500
    assert aggregate.average_api_calls == 15
    assert aggregate.average_ai_credits == 0.75
    assert aggregate.average_premium_requests == 0.375
    assert aggregate.structured_usage_complete_rate == 0.5
    assert aggregate.average_knowledge_files == 30
    assert aggregate.average_knowledge_pruned == 6


def test_github_summary_renders_performance_metrics() -> None:
    summary = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=_metrics(duration=4.0, scale=1))],
        run_id="run",
    )

    markdown = summary.render_github_metrics_markdown()

    assert "## Performance" in markdown
    assert "Avg total tokens" in markdown
    assert "Avg API calls" in markdown
    assert "Avg AI credits" in markdown
    assert "Avg premium requests" in markdown
    assert "Complete structured usage" in markdown
    assert "| 10.0 | 1.0 | 9.0 | 0.5000 | 0.2500 | 100.0% | 0.0 |" in markdown
    assert "Avg knowledge files" in markdown


def test_generic_result_does_not_serialize_pr_review_metrics(tmp_path: Path) -> None:
    result = create_bugfix_result(metrics=AgentMetrics(execution_time=4.0))
    result.save(tmp_path, "results.jsonl")

    saved_metrics = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8"))["metrics"]

    for field in (
        "cached_tokens",
        "cache_creation_tokens",
        "reasoning_tokens",
        "total_tokens",
        "api_calls",
        "failed_api_calls",
        "usage_api_calls",
        "ai_credits",
        "premium_requests",
        "usage_complete",
        "malformed_records",
        "knowledge_files",
        "knowledge_pruned",
    ):
        assert field not in saved_metrics


def test_code_review_result_serializes_structured_metrics(tmp_path: Path) -> None:
    result = create_codereview_result(metrics=_metrics(duration=4.0, scale=1))
    result.save(tmp_path, "results.jsonl")

    saved_metrics = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8"))["metrics"]

    assert saved_metrics["total_tokens"] == 1000
    assert saved_metrics["api_calls"] == 10
    assert saved_metrics["ai_credits"] == 0.5
    assert saved_metrics["reasoning_tokens"] == 25
    assert saved_metrics["premium_requests"] == 0.25
    assert saved_metrics["usage_complete"] is True
    assert saved_metrics["malformed_records"] == 0
    assert saved_metrics["knowledge_files"] == 20
    assert saved_metrics["knowledge_pruned"] == 4


def test_code_review_result_preserves_nullable_structured_metrics(tmp_path: Path) -> None:
    result = create_codereview_result(
        metrics=AgentMetrics(
            execution_time=4.0,
            reasoning_tokens=None,
            premium_requests=None,
            usage_complete=True,
            malformed_records=0,
            knowledge_files=20,
            knowledge_pruned=4,
        )
    )
    result.save(tmp_path, "results.jsonl")

    saved_metrics = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8"))["metrics"]

    assert "reasoning_tokens" in saved_metrics
    assert saved_metrics["reasoning_tokens"] is None
    assert "premium_requests" in saved_metrics
    assert saved_metrics["premium_requests"] is None
