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
        cached_tokens=100 * scale,
        cache_creation_tokens=50 * scale,
        reasoning_tokens=25 * scale,
        api_calls=10 * scale,
        failed_api_calls=scale - 1,
        usage_api_calls=9 * scale,
        premium_requests=0.5 * scale,
        usage_complete=True,
        malformed_records=0,
        knowledge_files=40 * scale,
        knowledge_pruned=20 * scale,
        knowledge_used=5 * scale,
        knowledge_suppressed=2 * scale,
        sub_skills_executed=3 * scale,
        sub_skills_skipped=scale,
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
    assert summary.average_cached_tokens == 150
    assert summary.average_cache_creation_tokens == 75
    assert summary.average_reasoning_tokens == 37.5
    assert summary.average_api_calls == 15
    assert summary.average_failed_api_calls == 0.5
    assert summary.average_usage_api_calls == 13.5
    assert summary.average_premium_requests == 0.75
    assert summary.average_malformed_records == 0
    assert summary.average_knowledge_files == 60
    assert summary.average_knowledge_pruned == 30
    assert summary.average_knowledge_used == 7.5
    assert summary.average_knowledge_suppressed == 3
    assert summary.average_sub_skills_executed == 4.5
    assert summary.average_sub_skills_skipped == 1.5
    assert summary.token_coverage_rate == 1.0
    assert summary.credit_coverage_rate == 1.0
    assert summary.usage_complete_rate == 1.0
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
    assert serialized["token_coverage_rate"] == 0.0
    assert serialized["credit_coverage_rate"] == 0.0
    assert serialized["usage_complete_rate"] == 0.0


def test_aggregate_preserves_missing_legacy_coverage_as_none() -> None:
    summary = CodeReviewResultSummary.model_validate(
        {
            "run_id": "legacy",
            "agent_name": "GitHub Copilot",
            "model": "legacy-model",
            "category": "code-review",
            "benchmark_version": "0.7.0",
            "date": "2026-01-01T00:00:00Z",
            "total": 1,
            "average_duration": 1.0,
            "judge_model": "legacy-judge",
        }
    )

    aggregate = CodeReviewLeaderboardAggregate.from_runs([summary])

    assert aggregate.token_coverage_rate is None
    assert aggregate.credit_coverage_rate is None
    assert aggregate.usage_complete_rate is None


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
    assert aggregate.average_api_calls == 15
    assert aggregate.average_knowledge_files == 60
    assert aggregate.average_knowledge_pruned == 30
    assert aggregate.average_knowledge_used == 7.5
    assert aggregate.average_knowledge_suppressed == 3
    assert aggregate.average_sub_skills_executed == 4.5
    assert aggregate.average_sub_skills_skipped == 1.5
    assert aggregate.token_coverage_rate == 1.0
    assert aggregate.credit_coverage_rate == 1.0
    assert aggregate.usage_complete_rate == 1.0
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


def test_result_json_persists_pr_review_diagnostics(tmp_path) -> None:
    result = create_codereview_result(metrics=_metrics(duration=4.0, scale=1))
    result.save(tmp_path, "results.jsonl")

    saved_metrics = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8"))["metrics"]

    assert saved_metrics["prompt_tokens"] == 900
    assert saved_metrics["completion_tokens"] == 100
    assert saved_metrics["total_tokens"] == 1000
    assert saved_metrics["ai_credits"] == 0.5
    assert saved_metrics["cached_tokens"] == 100
    assert saved_metrics["cache_creation_tokens"] == 50
    assert saved_metrics["reasoning_tokens"] == 25
    assert saved_metrics["api_calls"] == 10
    assert saved_metrics["failed_api_calls"] == 0
    assert saved_metrics["usage_api_calls"] == 9
    assert saved_metrics["premium_requests"] == 0.5
    assert saved_metrics["usage_complete"] is True
    assert saved_metrics["malformed_records"] == 0
    assert saved_metrics["knowledge_files"] == 40
    assert saved_metrics["knowledge_pruned"] == 20
    assert saved_metrics["knowledge_used"] == 5
    assert saved_metrics["knowledge_suppressed"] == 2
    assert saved_metrics["sub_skills_executed"] == 3
    assert saved_metrics["sub_skills_skipped"] == 1


def test_summary_and_leaderboard_schemas_include_pr_review_diagnostics() -> None:
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
            "usage_complete_rate",
            "average_malformed_records",
            "average_knowledge_files",
            "average_knowledge_pruned",
            "average_knowledge_used",
            "average_knowledge_suppressed",
            "average_sub_skills_executed",
            "average_sub_skills_skipped",
            "token_coverage_rate",
            "credit_coverage_rate",
        ):
            assert diagnostic in payload
