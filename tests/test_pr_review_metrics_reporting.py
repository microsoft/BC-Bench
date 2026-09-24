import json

import pytest

from bcbench.agent.pr_review.definitions import DEFAULT_PR_REVIEW_DEFINITION_ID, get_pr_review_definition
from bcbench.results.codereview import CodeReviewResultSummary
from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate, ExecutionBasedLeaderboardAggregate
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary
from bcbench.types import AgentHarness, AgentMetrics, PRReviewMetrics
from tests.conftest import create_codereview_result


def _metrics(*, duration: float, scale: int) -> PRReviewMetrics:
    return PRReviewMetrics(
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
        models=["claude-sonnet-5", "gpt-5.4"],
        usage_complete=True,
        malformed_records=0,
        knowledge_files=40 * scale,
        knowledge_pruned=20 * scale,
        knowledge_used=5 * scale,
        knowledge_suppressed=2 * scale,
        sub_skills_executed=3 * scale,
        sub_skills_skipped=scale,
        copilot_cli_version="1.0.83",
        bcquality_repository="microsoft/BCQuality",
        bcquality_commit="a" * 40,
        bcquality_version="1.6",
        leaf_model="gpt-5.4",
        leaf_execution="serial",
        max_leaf_concurrency=4,
        bcquality_source_snapshot="b" * 64,
        review_process_count=2,
        cli_timeout_minutes=30,
        minimum_severity="Medium",
        agent_minimum_severity="Medium",
        review_source="local",
    )


def _defined_metrics(*, duration: float, scale: int) -> PRReviewMetrics:
    definition = get_pr_review_definition(DEFAULT_PR_REVIEW_DEFINITION_ID)
    return _metrics(duration=duration, scale=scale).model_copy(update={"definition_id": definition.id, "definition_name": definition.display_name})


def test_pr_review_provenance_fields_are_code_review_specific() -> None:
    provenance_fields = {
        "copilot_cli_version",
        "bcquality_repository",
        "bcquality_commit",
        "bcquality_version",
        "definition_id",
        "definition_name",
    }

    assert provenance_fields <= CodeReviewResultSummary.model_fields.keys()
    assert provenance_fields <= CodeReviewLeaderboardAggregate.model_fields.keys()
    assert provenance_fields.isdisjoint(ExecutionBasedEvaluationResultSummary.model_fields)
    assert provenance_fields.isdisjoint(ExecutionBasedLeaderboardAggregate.model_fields)


def test_summary_aggregates_public_pr_review_metrics() -> None:
    summary = CodeReviewResultSummary.from_results(
        [
            create_codereview_result(instance_id="proj__review-1", agent_name=AgentHarness.PR_REVIEW, metrics=_metrics(duration=4.0, scale=1)),
            create_codereview_result(instance_id="proj__review-2", agent_name=AgentHarness.PR_REVIEW, metrics=_metrics(duration=6.0, scale=2)),
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
    assert summary.copilot_cli_version == "1.0.83"
    assert summary.bcquality_repository == "microsoft/BCQuality"
    assert summary.bcquality_commit == "a" * 40
    assert summary.bcquality_version == "1.6"
    assert summary.leaf_model == "gpt-5.4"
    assert summary.leaf_execution == "serial"
    assert summary.max_leaf_concurrency == 4
    assert summary.bcquality_source_snapshot == "b" * 64
    assert summary.cli_timeout_minutes == 30
    assert summary.minimum_severity == "Medium"
    assert summary.agent_minimum_severity == "Medium"
    assert summary.review_source == "local"


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
    assert serialized["usage_complete_rate"] is None


def test_summary_uses_only_available_usage_completeness_values() -> None:
    unavailable = _metrics(duration=4.0, scale=1).model_copy(update={"usage_complete": None})
    complete = _metrics(duration=5.0, scale=1)
    incomplete = _metrics(duration=6.0, scale=1).model_copy(update={"usage_complete": False})

    summary = CodeReviewResultSummary.from_results(
        [
            create_codereview_result(instance_id="proj__review-1", agent_name=AgentHarness.PR_REVIEW, metrics=unavailable),
            create_codereview_result(instance_id="proj__review-2", agent_name=AgentHarness.PR_REVIEW, metrics=complete),
            create_codereview_result(instance_id="proj__review-3", agent_name=AgentHarness.PR_REVIEW, metrics=incomplete),
        ],
        run_id="run",
    )

    assert summary.usage_complete_rate == 0.5


def test_summary_omits_inconsistent_runtime_provenance(caplog) -> None:
    first = _metrics(duration=4.0, scale=1)
    second = _metrics(duration=6.0, scale=2).model_copy(update={"bcquality_commit": "b" * 40})

    summary = CodeReviewResultSummary.from_results(
        [
            create_codereview_result(instance_id="proj__review-1", agent_name=AgentHarness.PR_REVIEW, metrics=first),
            create_codereview_result(instance_id="proj__review-2", agent_name=AgentHarness.PR_REVIEW, metrics=second),
        ],
        run_id="run",
    )

    assert summary.bcquality_commit is None
    assert "inconsistent bcquality_commit" in caplog.text


def test_summary_excludes_unavailable_findings_diagnostics() -> None:
    unavailable = _metrics(duration=4.0, scale=1).model_copy(
        update={
            "knowledge_used": None,
            "knowledge_suppressed": None,
            "sub_skills_executed": None,
            "sub_skills_skipped": None,
        }
    )
    measured = _metrics(duration=6.0, scale=2)

    summary = CodeReviewResultSummary.from_results(
        [
            create_codereview_result(agent_name=AgentHarness.PR_REVIEW, metrics=unavailable),
            create_codereview_result(agent_name=AgentHarness.PR_REVIEW, metrics=measured),
        ],
        run_id="run",
    )

    assert summary.average_knowledge_used == measured.knowledge_used
    assert summary.average_knowledge_suppressed == measured.knowledge_suppressed
    assert summary.average_sub_skills_executed == measured.sub_skills_executed
    assert summary.average_sub_skills_skipped == measured.sub_skills_skipped


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

    assert summary.definition_id is None
    assert summary.definition_name is None
    assert aggregate.definition_id is None
    assert aggregate.definition_name is None
    assert aggregate.token_coverage_rate is None
    assert aggregate.credit_coverage_rate is None
    assert aggregate.usage_complete_rate is None


def test_leaderboard_propagates_public_pr_review_metrics() -> None:
    first = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", agent_name=AgentHarness.PR_REVIEW, metrics=_metrics(duration=4.0, scale=1))],
        run_id="one",
    )
    second = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", agent_name=AgentHarness.PR_REVIEW, metrics=_metrics(duration=6.0, scale=2))],
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
    assert aggregate.copilot_cli_version == "1.0.83"
    assert aggregate.bcquality_repository == "microsoft/BCQuality"
    assert aggregate.bcquality_commit == "a" * 40
    assert aggregate.bcquality_version == "1.6"
    assert aggregate.leaf_model == "gpt-5.4"
    assert aggregate.leaf_execution == "serial"
    assert aggregate.max_leaf_concurrency == 4
    assert aggregate.bcquality_source_snapshot == "b" * 64
    assert aggregate.cli_timeout_minutes == 30
    assert aggregate.minimum_severity == "Medium"
    assert aggregate.agent_minimum_severity == "Medium"
    assert aggregate.review_source == "local"


def test_github_summary_renders_only_public_performance_metrics() -> None:
    summary = CodeReviewResultSummary.from_results(
        [create_codereview_result(instance_id="proj__review-1", agent_name=AgentHarness.PR_REVIEW, metrics=_metrics(duration=4.0, scale=1))],
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
    result = create_codereview_result(agent_name=AgentHarness.PR_REVIEW, metrics=_metrics(duration=4.0, scale=1))
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
    assert saved_metrics["usage_complete"] is True
    assert saved_metrics["malformed_records"] == 0
    assert saved_metrics["knowledge_files"] == 40
    assert saved_metrics["knowledge_pruned"] == 20
    assert saved_metrics["knowledge_used"] == 5
    assert saved_metrics["knowledge_suppressed"] == 2
    assert saved_metrics["sub_skills_executed"] == 3
    assert saved_metrics["sub_skills_skipped"] == 1
    assert saved_metrics["premium_requests"] == 0.5
    assert saved_metrics["models"] == ["claude-sonnet-5", "gpt-5.4"]
    assert saved_metrics["copilot_cli_version"] == "1.0.83"
    assert saved_metrics["leaf_model"] == "gpt-5.4"
    assert saved_metrics["leaf_execution"] == "serial"
    assert saved_metrics["max_leaf_concurrency"] == 4
    assert saved_metrics["bcquality_source_snapshot"] == "b" * 64
    assert saved_metrics["review_process_count"] == 2


def test_summary_and_leaderboard_schemas_include_pr_review_diagnostics() -> None:
    summary = CodeReviewResultSummary.from_results(
        [create_codereview_result(agent_name=AgentHarness.PR_REVIEW, metrics=_metrics(duration=4.0, scale=1))],
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


def test_named_definition_is_persisted_and_part_of_code_review_combination_identity() -> None:
    named = CodeReviewResultSummary.from_results(
        [create_codereview_result(agent_name=AgentHarness.PR_REVIEW, metrics=_defined_metrics(duration=4.0, scale=1))],
        run_id="named",
    )
    legacy = CodeReviewResultSummary.from_results(
        [create_codereview_result(agent_name=AgentHarness.PR_REVIEW, metrics=_metrics(duration=4.0, scale=1))],
        run_id="legacy",
    )

    assert named.definition_id == DEFAULT_PR_REVIEW_DEFINITION_ID
    assert named.definition_name == "BC PR Review — Production / Sol / Luna / Serial v1"
    assert named.combination_key() != legacy.combination_key()
    assert CodeReviewLeaderboardAggregate.from_runs([named]).definition_id == DEFAULT_PR_REVIEW_DEFINITION_ID

    with pytest.raises(ValueError, match="different combinations"):
        CodeReviewLeaderboardAggregate.from_runs([named, legacy])

    different_definition = named.model_copy(update={"definition_id": "another-registered-definition"})
    assert named.combination_key() != different_definition.combination_key()
    with pytest.raises(ValueError, match="different combinations"):
        CodeReviewLeaderboardAggregate.from_runs([named, different_definition])


def test_generic_code_review_rows_retain_existing_combination_behavior() -> None:
    first = CodeReviewResultSummary.from_results(
        [create_codereview_result(agent_name=AgentHarness.COPILOT, model="gpt-5.6-sol", metrics=AgentMetrics(execution_time=4.0))],
        run_id="first",
    )
    second = CodeReviewResultSummary.from_results(
        [create_codereview_result(agent_name=AgentHarness.COPILOT, model="gpt-5.6-sol", metrics=AgentMetrics(execution_time=5.0))],
        run_id="second",
    )

    aggregate = CodeReviewLeaderboardAggregate.from_runs([first, second])

    assert first.definition_id is None
    assert second.definition_id is None
    assert first.combination_key() == second.combination_key()
    assert aggregate.num_runs == 2


def test_code_review_result_rejects_an_unregistered_definition_name() -> None:
    invalid_metrics = _metrics(duration=4.0, scale=1).model_copy(update={"definition_id": "unregistered", "definition_name": "Arbitrary"})

    with pytest.raises(ValueError, match="Unknown BC PR Review definition"):
        create_codereview_result(agent_name=AgentHarness.PR_REVIEW, metrics=invalid_metrics)
