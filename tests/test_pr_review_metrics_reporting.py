import json

from bcbench.results.codereview import CodeReviewResultSummary
from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate
from bcbench.types import AgentMetrics
from tests.conftest import create_codereview_result


def _metrics(*, duration: float, scale: int) -> AgentMetrics:
    return AgentMetrics(
        execution_time=duration,
        prompt_tokens=900 * scale,
        completion_tokens=100 * scale,
        total_tokens=1000 * scale,
        ai_credits=0.5 * scale,
    )


def test_summary_aggregates_public_pr_review_metrics() -> None:
    summary = CodeReviewResultSummary.from_results(
        [
            create_codereview_result(instance_id="proj__review-1", metrics=_metrics(duration=4.0, scale=1)),
            create_codereview_result(instance_id="proj__review-2", metrics=_metrics(duration=6.0, scale=2)),
        ],
        run_id="run",
    )

    assert summary.average_duration == 5
    assert summary.average_prompt_tokens == 1350
    assert summary.average_completion_tokens == 150
    assert summary.average_total_tokens == 1500
    assert summary.average_ai_credits == 0.75
    assert summary.valid_review_output_rate == 1.0


def test_summary_preserves_unavailable_usage_as_none() -> None:
    summary = CodeReviewResultSummary.from_results(
        [create_codereview_result(metrics=AgentMetrics(execution_time=4.0))],
        run_id="run",
    )

    serialized = summary.to_dict()

    assert serialized["average_prompt_tokens"] is None
    assert serialized["average_completion_tokens"] is None
    assert serialized["average_total_tokens"] is None
    assert serialized["average_ai_credits"] is None


def test_leaderboard_propagates_public_pr_review_metrics() -> None:
    first = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=_metrics(duration=4.0, scale=1))],
        run_id="one",
    )
    second = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=_metrics(duration=6.0, scale=2))],
        run_id="two",
    )

    aggregate = CodeReviewLeaderboardAggregate.from_runs([first, second])

    assert aggregate.average_duration == 5
    assert aggregate.average_prompt_tokens == 1350
    assert aggregate.average_completion_tokens == 150
    assert aggregate.average_total_tokens == 1500
    assert aggregate.average_ai_credits == 0.75
    assert aggregate.valid_review_output_rate == 1.0


def test_github_summary_renders_only_public_performance_metrics() -> None:
    summary = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", metrics=_metrics(duration=4.0, scale=1))],
        run_id="run",
    )

    markdown = summary.render_github_metrics_markdown()

    assert "## Performance" in markdown
    assert "Avg prompt tokens" in markdown
    assert "Avg completion tokens" in markdown
    assert "Avg total tokens" in markdown
    assert "Avg AI credits" in markdown
    for diagnostic in ("API calls", "knowledge", "cached", "reasoning", "failed API", "usage", "premium", "malformed"):
        assert diagnostic not in markdown


def test_result_json_excludes_raw_only_diagnostics(tmp_path) -> None:
    result = create_codereview_result(metrics=_metrics(duration=4.0, scale=1))
    result.save(tmp_path, "results.jsonl")

    saved_metrics = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8"))["metrics"]

    assert saved_metrics["prompt_tokens"] == 900
    assert saved_metrics["completion_tokens"] == 100
    assert saved_metrics["total_tokens"] == 1000
    assert saved_metrics["ai_credits"] == 0.5
    for diagnostic in (
        "cached_tokens",
        "cache_creation_tokens",
        "reasoning_tokens",
        "failed_api_calls",
        "usage_api_calls",
        "premium_requests",
        "usage_complete",
        "malformed_records",
    ):
        assert diagnostic not in saved_metrics


def test_summary_and_leaderboard_schemas_exclude_raw_only_diagnostics() -> None:
    summary = CodeReviewResultSummary.from_results(
        [create_codereview_result(metrics=_metrics(duration=4.0, scale=1))],
        run_id="run",
    )
    aggregate = CodeReviewLeaderboardAggregate.from_runs([summary])

    for payload in (summary.model_dump(), aggregate.model_dump()):
        for diagnostic in (
            "average_cached_tokens",
            "average_cache_creation_tokens",
            "average_reasoning_tokens",
            "average_api_calls",
            "average_failed_api_calls",
            "average_usage_api_calls",
            "average_premium_requests",
            "structured_usage_complete_rate",
            "average_malformed_records",
            "average_knowledge_files",
            "average_knowledge_pruned",
        ):
            assert diagnostic not in payload
