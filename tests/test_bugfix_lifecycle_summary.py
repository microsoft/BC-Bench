import json

import pytest
from pydantic import ValidationError

from bcbench.results.bugfix import (
    BugFixMetricName,
    BugFixMetricSummary,
    BugFixPhaseResult,
    BugFixPhaseStatus,
    BugFixResultSummary,
)
from bcbench.results.leaderboard import BugFixLeaderboardAggregate, Leaderboard
from bcbench.types import EvaluationCategory, ExperimentConfiguration
from evaluator.scores import FixBuild, FixQuality, GeneratedPairTransition, GeneratedTestValidity, Resolution
from tests.conftest import create_bugfix_result, create_testgen_result


def _phase(status: BugFixPhaseStatus) -> BugFixPhaseResult:
    return BugFixPhaseResult(status=status)


def _checkpointed_result(
    instance_id: str,
    *,
    test_red: BugFixPhaseStatus,
    test_gold: BugFixPhaseStatus,
    fix_build: BugFixPhaseStatus,
    generated_pair: BugFixPhaseStatus,
    benchmark_fix: BugFixPhaseStatus,
):
    return create_bugfix_result(
        instance_id=instance_id,
        runtime_isolation="database-checkpointed-single-container",
        test_red=_phase(test_red),
        test_gold=_phase(test_gold),
        fix_build=_phase(fix_build),
        generated_pair=_phase(generated_pair),
        benchmark_fix=_phase(benchmark_fix),
    )


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (
            [BugFixPhaseStatus.PASSED, BugFixPhaseStatus.FAILED],
            {"successes": 1, "determined_failures": 1, "unknown": 0, "scheduled": 2, "rate": 0.5, "coverage": 1.0},
        ),
        (
            [BugFixPhaseStatus.PASSED, BugFixPhaseStatus.INVALID_SUBMISSION, BugFixPhaseStatus.INFRASTRUCTURE_ERROR, BugFixPhaseStatus.NOT_RUN],
            {"successes": 1, "determined_failures": 1, "unknown": 2, "scheduled": 4, "rate": 0.5, "coverage": 0.5},
        ),
        (
            [BugFixPhaseStatus.INFRASTRUCTURE_ERROR, BugFixPhaseStatus.NOT_RUN],
            {"successes": 0, "determined_failures": 0, "unknown": 2, "scheduled": 2, "rate": None, "coverage": 0.0},
        ),
    ],
)
def test_metric_summary_tracks_rate_and_coverage(statuses, expected):
    assert BugFixMetricSummary.from_statuses(statuses).model_dump() == expected


def test_checkpointed_summary_calculates_all_production_metrics():
    results = [
        _checkpointed_result(
            "test__passed",
            test_red=BugFixPhaseStatus.PASSED,
            test_gold=BugFixPhaseStatus.PASSED,
            fix_build=BugFixPhaseStatus.PASSED,
            generated_pair=BugFixPhaseStatus.PASSED,
            benchmark_fix=BugFixPhaseStatus.PASSED,
        ),
        _checkpointed_result(
            "test__failed",
            test_red=BugFixPhaseStatus.FAILED,
            test_gold=BugFixPhaseStatus.PASSED,
            fix_build=BugFixPhaseStatus.FAILED,
            generated_pair=BugFixPhaseStatus.PASSED,
            benchmark_fix=BugFixPhaseStatus.INVALID_SUBMISSION,
        ),
        _checkpointed_result(
            "test__infrastructure",
            test_red=BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
            test_gold=BugFixPhaseStatus.PASSED,
            fix_build=BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
            generated_pair=BugFixPhaseStatus.PASSED,
            benchmark_fix=BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
        ),
        _checkpointed_result(
            "test__not-run",
            test_red=BugFixPhaseStatus.NOT_RUN,
            test_gold=BugFixPhaseStatus.PASSED,
            fix_build=BugFixPhaseStatus.NOT_RUN,
            generated_pair=BugFixPhaseStatus.PASSED,
            benchmark_fix=BugFixPhaseStatus.NOT_RUN,
        ),
    ]
    results = [
        results[0].model_copy(update={"resolved": False, "build": False}),
        results[1].model_copy(update={"resolved": True, "build": True}),
        results[2].model_copy(update={"resolved": True, "build": True}),
        results[3].model_copy(update={"resolved": True, "build": True}),
    ]

    summary = BugFixResultSummary.from_results(results, run_id="run")

    assert summary.runtime_isolation == "database-checkpointed-single-container"
    assert summary.resolved == 1
    assert summary.failed == 1
    assert summary.build == 1
    assert summary.percentage == 50.0
    assert summary.instance_results == {
        "test__passed": True,
        "test__failed": False,
    }
    assert set(summary.metric_summaries) == set(BugFixMetricName)
    for metric_summary in summary.metric_summaries.values():
        assert metric_summary == BugFixMetricSummary(
            successes=1,
            determined_failures=1,
            unknown=2,
            scheduled=4,
            rate=0.5,
            coverage=0.5,
        )
    markdown = summary.render_github_metrics_markdown()
    assert "Generated Test Validity: 50.0% (coverage 50.0%, 2/4 determined)" in markdown
    assert "Resolution: 50.0% (coverage 50.0%, 2/4 determined)" in markdown


def test_failed_fix_build_is_a_determined_resolution_failure():
    result = _checkpointed_result(
        "test__failed-build",
        test_red=BugFixPhaseStatus.PASSED,
        test_gold=BugFixPhaseStatus.PASSED,
        fix_build=BugFixPhaseStatus.FAILED,
        generated_pair=BugFixPhaseStatus.NOT_RUN,
        benchmark_fix=BugFixPhaseStatus.NOT_RUN,
    )

    summary = BugFixResultSummary.from_results([result], run_id="run")

    assert summary.failed == 1
    assert summary.percentage == 0.0
    assert summary.instance_results == {"test__failed-build": False}


def test_package_normalized_summary_preserves_legacy_headline():
    summary = BugFixResultSummary.from_results(
        [
            create_bugfix_result(instance_id="test__passed", resolved=True, build=True),
            create_bugfix_result(instance_id="test__failed", resolved=False, build=False),
            create_bugfix_result(
                instance_id="test__infrastructure",
                resolved=False,
                build=True,
                infrastructure_failure=True,
            ),
        ],
        run_id="run",
    )

    assert summary.runtime_isolation == "package-normalized"
    assert summary.resolved == 1
    assert summary.failed == 1
    assert summary.infrastructure_failed == 1
    assert summary.build == 1
    assert summary.percentage == 50.0
    assert summary.metric_summaries[BugFixMetricName.GENERATED_TEST_VALIDITY].rate is None
    assert summary.metric_summaries[BugFixMetricName.GENERATED_TEST_VALIDITY].coverage == 0.0
    assert summary.metric_summaries[BugFixMetricName.RESOLUTION].rate == 0.5
    assert summary.metric_summaries[BugFixMetricName.RESOLUTION].coverage == pytest.approx(2 / 3)


def test_legacy_package_normalized_summary_reconstructs_metric_summaries():
    legacy_payload = {
        "total": 4,
        "resolved": 1,
        "failed": 1,
        "infrastructure_failed": 2,
        "build": 1,
        "percentage": 50.0,
        "date": "2025-01-15",
        "model": "gpt-4o",
        "category": "bug-fix",
        "agent_name": "copilot",
        "average_duration": 100.0,
        "average_prompt_tokens": 1000.0,
        "average_completion_tokens": 500.0,
        "benchmark_version": "0.1.0",
    }
    summary = BugFixResultSummary.model_validate(legacy_payload)

    expected_reconstructed = BugFixMetricSummary(
        successes=1,
        determined_failures=1,
        unknown=2,
        scheduled=4,
        rate=0.5,
        coverage=0.5,
    )
    assert summary.metric_summaries[BugFixMetricName.RESOLUTION] == expected_reconstructed
    assert summary.metric_summaries[BugFixMetricName.FIX_BUILD] == expected_reconstructed

    for metric in (
        BugFixMetricName.GENERATED_TEST_VALIDITY,
        BugFixMetricName.GENERATED_PAIR_TRANSITION,
        BugFixMetricName.FIX_QUALITY,
    ):
        assert summary.metric_summaries[metric] == BugFixMetricSummary(
            successes=0,
            determined_failures=0,
            unknown=4,
            scheduled=4,
            rate=None,
            coverage=0.0,
        )
    assert summary.instance_results_complete is False
    assert summary.instance_results == {}

    restored = BugFixResultSummary.model_validate_json(summary.model_dump_json())

    assert restored == summary


def test_legacy_package_normalized_summary_aggregates_with_new_summary():
    new_summary = BugFixResultSummary.from_results(
        [
            create_bugfix_result(instance_id="test__1", resolved=True, build=True),
            create_bugfix_result(instance_id="test__2", resolved=True, build=True),
        ],
        run_id="new",
    )
    legacy_payload = new_summary.model_dump(mode="json")
    legacy_payload.pop("metric_summaries")
    legacy_payload.update(
        {
            "resolved": 0,
            "failed": 2,
            "build": 0,
            "percentage": 0.0,
            "instance_results": {
                "test__1": False,
                "test__2": False,
            },
        }
    )
    old_summary = BugFixResultSummary.model_validate(legacy_payload)

    aggregate = BugFixLeaderboardAggregate.from_runs([old_summary, new_summary])

    assert aggregate.metric_averages[BugFixMetricName.RESOLUTION] == 0.5
    assert aggregate.metric_coverages[BugFixMetricName.RESOLUTION] == 1.0


def test_bugfix_summary_rejects_empty_results():
    with pytest.raises(ValueError, match="empty"):
        BugFixResultSummary.from_results([], run_id="run")


def test_bugfix_summary_rejects_duplicate_unknown_instance_results():
    result = create_bugfix_result(
        instance_id="test__infrastructure",
        resolved=False,
        infrastructure_failure=True,
    )

    with pytest.raises(ValueError, match="duplicate instance_id"):
        BugFixResultSummary.from_results([result, result], run_id="run")


def test_bugfix_summary_rejects_non_bugfix_results():
    with pytest.raises(ValueError, match="BugFixResult"):
        BugFixResultSummary.from_results(
            [
                create_bugfix_result(instance_id="test__bugfix"),
                create_testgen_result(instance_id="test__test-generation"),
            ],
            run_id="run",
        )


def test_bugfix_summary_rejects_mixed_categories():
    results = [
        create_bugfix_result(instance_id="test__bugfix"),
        create_bugfix_result(instance_id="test__wrong-category").model_copy(update={"category": EvaluationCategory.TEST_GENERATION}),
    ]

    with pytest.raises(ValueError, match="category"):
        BugFixResultSummary.from_results(results, run_id="run")


@pytest.mark.parametrize(
    ("field", "update"),
    [
        ("model", {"model": "claude-sonnet-4"}),
        ("agent_name", {"agent_name": "claude-code"}),
        ("agent_version", {"agent_version": "2.0.0"}),
        ("experiment", {"experiment": ExperimentConfiguration(custom_instructions=True)}),
    ],
)
def test_bugfix_summary_rejects_inconsistent_run_identity_fields(field, update):
    results = [
        create_bugfix_result(instance_id="test__first"),
        create_bugfix_result(instance_id="test__second").model_copy(update=update),
    ]

    with pytest.raises(ValueError, match=field):
        BugFixResultSummary.from_results(results, run_id="run")


def test_bugfix_summary_rejects_mixed_runtime_isolation_before_aggregation():
    with pytest.raises(ValueError, match="runtime_isolation"):
        BugFixResultSummary.from_results(
            [
                create_bugfix_result(instance_id="test__package"),
                _checkpointed_result(
                    "test__checkpointed",
                    test_red=BugFixPhaseStatus.PASSED,
                    test_gold=BugFixPhaseStatus.PASSED,
                    fix_build=BugFixPhaseStatus.PASSED,
                    generated_pair=BugFixPhaseStatus.PASSED,
                    benchmark_fix=BugFixPhaseStatus.PASSED,
                ),
            ],
            run_id="run",
        )


def _valid_metric_summary_payload():
    return BugFixMetricSummary(
        successes=1,
        determined_failures=1,
        unknown=1,
        scheduled=3,
        rate=0.5,
        coverage=2 / 3,
    ).model_dump(mode="json")


@pytest.mark.parametrize(
    "update",
    [
        {"successes": -1},
        {"determined_failures": -1},
        {"unknown": -1},
        {"scheduled": -1},
        {"scheduled": 4},
        {"rate": 0.25},
        {"rate": None},
        {"coverage": 0.5},
    ],
)
def test_metric_summary_rejects_invalid_persisted_values(update):
    payload = {**_valid_metric_summary_payload(), **update}

    with pytest.raises(ValidationError):
        BugFixMetricSummary.model_validate(payload)


def test_metric_summary_requires_none_rate_when_nothing_is_determined():
    with pytest.raises(ValidationError):
        BugFixMetricSummary.model_validate(
            {
                "successes": 0,
                "determined_failures": 0,
                "unknown": 1,
                "scheduled": 1,
                "rate": 0.0,
                "coverage": 0.0,
            }
        )


def test_metric_summary_requires_zero_coverage_when_nothing_is_scheduled():
    with pytest.raises(ValidationError):
        BugFixMetricSummary.model_validate(
            {
                "successes": 0,
                "determined_failures": 0,
                "unknown": 0,
                "scheduled": 0,
                "rate": None,
                "coverage": 0.1,
            }
        )


def test_bugfix_summary_rejects_partial_metric_summaries():
    summary = BugFixResultSummary.from_results([create_bugfix_result()], run_id="run")
    payload = summary.model_dump(mode="json")
    payload["metric_summaries"].pop(BugFixMetricName.RESOLUTION)

    with pytest.raises(ValidationError, match="metric_summaries"):
        BugFixResultSummary.model_validate(payload)


def test_checkpointed_summary_rejects_missing_metric_summaries():
    summary = BugFixResultSummary.from_results(
        [
            _checkpointed_result(
                "test__checkpointed",
                test_red=BugFixPhaseStatus.PASSED,
                test_gold=BugFixPhaseStatus.PASSED,
                fix_build=BugFixPhaseStatus.PASSED,
                generated_pair=BugFixPhaseStatus.PASSED,
                benchmark_fix=BugFixPhaseStatus.PASSED,
            )
        ],
        run_id="run",
    )
    payload = summary.model_dump(mode="json")
    payload.pop("metric_summaries")

    with pytest.raises(ValidationError, match="metric_summaries"):
        BugFixResultSummary.model_validate(payload)


def test_bugfix_summary_rejects_extra_metric_summaries():
    summary = BugFixResultSummary.from_results([create_bugfix_result()], run_id="run")
    payload = summary.model_dump(mode="json")
    payload["metric_summaries"]["UnexpectedMetric"] = _valid_metric_summary_payload()

    with pytest.raises(ValidationError, match="metric_summaries"):
        BugFixResultSummary.model_validate(payload)


def test_bugfix_summary_rejects_metric_scheduled_count_different_from_total():
    summary = BugFixResultSummary.from_results([create_bugfix_result()], run_id="run")
    payload = summary.model_dump(mode="json")
    payload["metric_summaries"][BugFixMetricName.FIX_QUALITY] = BugFixMetricSummary.from_statuses([BugFixPhaseStatus.NOT_RUN, BugFixPhaseStatus.NOT_RUN]).model_dump(mode="json")

    with pytest.raises(ValidationError, match="scheduled"):
        BugFixResultSummary.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("resolved", 0),
        ("failed", 0),
        ("infrastructure_failed", 0),
        ("build", 0),
        ("percentage", 0.0),
    ],
)
def test_bugfix_summary_rejects_contradictory_headline_projection(field, value):
    summary = BugFixResultSummary.from_results(
        [
            _checkpointed_result(
                "test__passed",
                test_red=BugFixPhaseStatus.PASSED,
                test_gold=BugFixPhaseStatus.PASSED,
                fix_build=BugFixPhaseStatus.PASSED,
                generated_pair=BugFixPhaseStatus.PASSED,
                benchmark_fix=BugFixPhaseStatus.PASSED,
            ),
            _checkpointed_result(
                "test__failed",
                test_red=BugFixPhaseStatus.FAILED,
                test_gold=BugFixPhaseStatus.PASSED,
                fix_build=BugFixPhaseStatus.FAILED,
                generated_pair=BugFixPhaseStatus.NOT_RUN,
                benchmark_fix=BugFixPhaseStatus.NOT_RUN,
            ),
            _checkpointed_result(
                "test__infrastructure",
                test_red=BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
                test_gold=BugFixPhaseStatus.PASSED,
                fix_build=BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
                generated_pair=BugFixPhaseStatus.NOT_RUN,
                benchmark_fix=BugFixPhaseStatus.NOT_RUN,
            ),
        ],
        run_id="run",
    )
    payload = summary.model_dump(mode="json")
    payload[field] = value

    with pytest.raises(ValidationError, match=field):
        BugFixResultSummary.model_validate(payload)


@pytest.mark.parametrize(
    "instance_results",
    [
        {"test__passed": True, "test__failed": True},
        {"test__passed": True},
        {"test__passed": True, "test__failed": False, "test__extra": False},
    ],
)
def test_bugfix_summary_rejects_wrong_instance_result_counts(instance_results):
    summary = BugFixResultSummary.from_results(
        [
            create_bugfix_result(instance_id="test__passed", resolved=True),
            create_bugfix_result(instance_id="test__failed", resolved=False),
        ],
        run_id="run",
    )
    payload = summary.model_dump(mode="json")
    payload["instance_results"] = instance_results

    with pytest.raises(ValidationError, match="instance_results"):
        BugFixResultSummary.model_validate(payload)


def test_bugfix_summary_rejects_nonempty_incomplete_instance_results():
    summary = BugFixResultSummary.from_results(
        [
            create_bugfix_result(instance_id="test__passed", resolved=True),
            create_bugfix_result(instance_id="test__failed", resolved=False),
        ],
        run_id="run",
    )
    payload = summary.model_dump(mode="json")
    payload["instance_results_complete"] = False

    with pytest.raises(ValidationError, match="instance_results"):
        BugFixResultSummary.model_validate(payload)


def test_bugfix_summary_rejects_complete_instance_results_with_missing_counts():
    summary = BugFixResultSummary.from_results(
        [
            create_bugfix_result(instance_id="test__passed", resolved=True),
            create_bugfix_result(instance_id="test__failed", resolved=False),
        ],
        run_id="run",
    )
    payload = summary.model_dump(mode="json")
    payload["instance_results"] = {"test__passed": True}

    with pytest.raises(ValidationError, match="instance_results"):
        BugFixResultSummary.model_validate(payload)


def test_checkpointed_result_exports_production_status_metadata():
    result = _checkpointed_result(
        "test__metadata",
        test_red=BugFixPhaseStatus.FAILED,
        test_gold=BugFixPhaseStatus.PASSED,
        fix_build=BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
        generated_pair=BugFixPhaseStatus.PASSED,
        benchmark_fix=BugFixPhaseStatus.INVALID_SUBMISSION,
    )

    assert result.category_metrics["generated_test_validity_status"] == "failed"
    assert result.category_metrics["generated_pair_transition_status"] == "failed"
    assert result.category_metrics["fix_build_status"] == "infrastructure_error"
    assert result.category_metrics["fix_quality_status"] == "invalid_submission"
    assert result.category_metrics["resolution_status"] == "invalid_submission"
    assert result.category_metrics["runtime_isolation"] == "database-checkpointed-single-container"


def test_runtime_isolation_is_part_of_combination_key():
    package_summary = BugFixResultSummary.from_results([create_bugfix_result()], run_id="package")
    checkpointed_summary = BugFixResultSummary.from_results(
        [
            _checkpointed_result(
                "test__1",
                test_red=BugFixPhaseStatus.PASSED,
                test_gold=BugFixPhaseStatus.PASSED,
                fix_build=BugFixPhaseStatus.PASSED,
                generated_pair=BugFixPhaseStatus.PASSED,
                benchmark_fix=BugFixPhaseStatus.PASSED,
            )
        ],
        run_id="checkpointed",
    )

    assert package_summary.combination_key()[-1] == "package-normalized"
    assert checkpointed_summary.combination_key()[-1] == "database-checkpointed-single-container"
    with pytest.raises(ValueError, match="different combinations"):
        BugFixLeaderboardAggregate.from_runs([package_summary, checkpointed_summary])


def test_bugfix_leaderboard_averages_metric_rates_and_coverages():
    first = BugFixResultSummary.from_results(
        [
            _checkpointed_result(
                "test__1",
                test_red=BugFixPhaseStatus.PASSED,
                test_gold=BugFixPhaseStatus.PASSED,
                fix_build=BugFixPhaseStatus.PASSED,
                generated_pair=BugFixPhaseStatus.PASSED,
                benchmark_fix=BugFixPhaseStatus.PASSED,
            ),
            _checkpointed_result(
                "test__2",
                test_red=BugFixPhaseStatus.FAILED,
                test_gold=BugFixPhaseStatus.PASSED,
                fix_build=BugFixPhaseStatus.FAILED,
                generated_pair=BugFixPhaseStatus.PASSED,
                benchmark_fix=BugFixPhaseStatus.FAILED,
            ),
        ],
        run_id="run-1",
    )
    second = BugFixResultSummary.from_results(
        [
            _checkpointed_result(
                "test__1",
                test_red=BugFixPhaseStatus.PASSED,
                test_gold=BugFixPhaseStatus.PASSED,
                fix_build=BugFixPhaseStatus.PASSED,
                generated_pair=BugFixPhaseStatus.PASSED,
                benchmark_fix=BugFixPhaseStatus.PASSED,
            ),
            _checkpointed_result(
                "test__2",
                test_red=BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
                test_gold=BugFixPhaseStatus.PASSED,
                fix_build=BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
                generated_pair=BugFixPhaseStatus.PASSED,
                benchmark_fix=BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
            ),
        ],
        run_id="run-2",
    )

    aggregate = BugFixLeaderboardAggregate.from_runs([first, second])

    assert aggregate.runtime_isolation == "database-checkpointed-single-container"
    assert aggregate.average == 0.75
    assert aggregate.metric_averages[BugFixMetricName.RESOLUTION] == 0.75
    assert aggregate.metric_coverages[BugFixMetricName.RESOLUTION] == 0.75


def test_five_legacy_count_only_runs_do_not_calculate_pass_hat_5():
    modern_summary = BugFixResultSummary.from_results(
        [
            create_bugfix_result(instance_id="test__passed", resolved=True),
            create_bugfix_result(instance_id="test__failed", resolved=False),
        ],
        run_id="modern",
    )
    legacy_payload = modern_summary.model_dump(mode="json")
    legacy_payload.pop("instance_results")
    legacy_payload.pop("instance_results_complete")
    legacy_payload.pop("metric_summaries")
    runs = [
        BugFixResultSummary.model_validate(
            {
                **legacy_payload,
                "github_run_id": f"legacy-{index}",
            }
        )
        for index in range(5)
    ]

    aggregate = BugFixLeaderboardAggregate.from_runs(runs)

    assert all(run.instance_results_complete is False for run in runs)
    assert aggregate.pass_hat_5 is None


def test_five_modern_runs_with_genuine_identities_calculate_pass_hat_5():
    runs = [
        BugFixResultSummary.from_results(
            [create_bugfix_result(instance_id="test__same", resolved=True)],
            run_id=f"modern-{index}",
        )
        for index in range(5)
    ]

    aggregate = BugFixLeaderboardAggregate.from_runs(runs)

    assert all(run.instance_results_complete is True for run in runs)
    assert aggregate.pass_hat_5 == 1.0


def test_checkpointed_bugfix_aggregate_round_trips():
    summary = BugFixResultSummary.from_results(
        [
            _checkpointed_result(
                "test__passed",
                test_red=BugFixPhaseStatus.PASSED,
                test_gold=BugFixPhaseStatus.PASSED,
                fix_build=BugFixPhaseStatus.PASSED,
                generated_pair=BugFixPhaseStatus.PASSED,
                benchmark_fix=BugFixPhaseStatus.PASSED,
            ),
            _checkpointed_result(
                "test__failed",
                test_red=BugFixPhaseStatus.FAILED,
                test_gold=BugFixPhaseStatus.PASSED,
                fix_build=BugFixPhaseStatus.FAILED,
                generated_pair=BugFixPhaseStatus.NOT_RUN,
                benchmark_fix=BugFixPhaseStatus.NOT_RUN,
            ),
        ],
        run_id="run",
    )
    aggregate = BugFixLeaderboardAggregate.from_runs([summary])

    restored = BugFixLeaderboardAggregate.model_validate_json(aggregate.model_dump_json())

    assert restored == aggregate


@pytest.mark.parametrize("field", ["metric_averages", "metric_coverages"])
def test_bugfix_aggregate_rejects_explicit_partial_metric_maps(field):
    summary = BugFixResultSummary.from_results([create_bugfix_result()], run_id="run")
    aggregate = BugFixLeaderboardAggregate.from_runs([summary])
    payload = aggregate.model_dump(mode="json")
    payload[field].pop(BugFixMetricName.RESOLUTION)

    with pytest.raises(ValidationError, match=field):
        BugFixLeaderboardAggregate.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("metric_averages", -0.1),
        ("metric_averages", 1.1),
        ("metric_coverages", -0.1),
        ("metric_coverages", 1.1),
    ],
)
def test_bugfix_aggregate_rejects_out_of_range_metric_values(field, value):
    summary = BugFixResultSummary.from_results([create_bugfix_result()], run_id="run")
    aggregate = BugFixLeaderboardAggregate.from_runs([summary])
    payload = aggregate.model_dump(mode="json")
    payload[field][BugFixMetricName.RESOLUTION] = value

    with pytest.raises(ValidationError, match=field):
        BugFixLeaderboardAggregate.model_validate(payload)


def test_bugfix_aggregate_rejects_resolution_average_disagreement():
    summary = BugFixResultSummary.from_results([create_bugfix_result(resolved=True)], run_id="run")
    aggregate = BugFixLeaderboardAggregate.from_runs([summary])
    payload = aggregate.model_dump(mode="json")
    payload["metric_averages"][BugFixMetricName.RESOLUTION] = 0.5

    with pytest.raises(ValidationError, match="Resolution"):
        BugFixLeaderboardAggregate.model_validate(payload)


def test_existing_package_normalized_leaderboard_data_loads(tmp_path):
    path = tmp_path / "bug-fix.json"
    path.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "total": 2,
                        "resolved": 1,
                        "failed": 1,
                        "infrastructure_failed": 0,
                        "build": 1,
                        "percentage": 50.0,
                        "date": "2025-01-15",
                        "model": "gpt-4o",
                        "category": "bug-fix",
                        "agent_name": "copilot",
                        "average_duration": 100.0,
                        "average_prompt_tokens": 1000.0,
                        "average_completion_tokens": 500.0,
                        "benchmark_version": "0.1.0",
                    }
                ],
                "aggregate": [
                    {
                        "model": "gpt-4o",
                        "agent_name": "copilot",
                        "category": "bug-fix",
                        "total": 2,
                        "num_runs": 1,
                        "average_duration": 100.0,
                        "benchmark_version": "0.1.0",
                        "average": 0.5,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    leaderboard = Leaderboard.load(path)

    assert isinstance(leaderboard.runs[0], BugFixResultSummary)
    assert leaderboard.runs[0].runtime_isolation == "package-normalized"
    assert leaderboard.runs[0].instance_results_complete is False
    assert leaderboard.runs[0].instance_results == {}
    assert set(leaderboard.runs[0].metric_summaries) == set(BugFixMetricName)
    assert isinstance(leaderboard.aggregate[0], BugFixLeaderboardAggregate)
    assert leaderboard.aggregate[0].runtime_isolation == "package-normalized"
    assert leaderboard.aggregate[0].pass_hat_5 is None
    assert set(leaderboard.aggregate[0].metric_averages) == set(BugFixMetricName)
    assert set(leaderboard.aggregate[0].metric_coverages) == set(BugFixMetricName)
    assert leaderboard.aggregate[0].metric_averages == {
        BugFixMetricName.GENERATED_TEST_VALIDITY: None,
        BugFixMetricName.GENERATED_PAIR_TRANSITION: None,
        BugFixMetricName.FIX_BUILD: 0.5,
        BugFixMetricName.FIX_QUALITY: None,
        BugFixMetricName.RESOLUTION: 0.5,
    }
    assert leaderboard.aggregate[0].metric_coverages == {
        BugFixMetricName.GENERATED_TEST_VALIDITY: 0.0,
        BugFixMetricName.GENERATED_PAIR_TRANSITION: 0.0,
        BugFixMetricName.FIX_BUILD: 1.0,
        BugFixMetricName.FIX_QUALITY: 0.0,
        BugFixMetricName.RESOLUTION: 1.0,
    }


@pytest.mark.parametrize(
    ("scorer", "metadata_key"),
    [
        (GeneratedTestValidity(), "generated_test_validity_status"),
        (GeneratedPairTransition(), "generated_pair_transition_status"),
        (FixBuild(), "fix_build_status"),
        (FixQuality(), "fix_quality_status"),
        (Resolution(), "resolution_status"),
    ],
)
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("passed", True),
        ("failed", False),
        ("invalid_submission", False),
        ("infrastructure_error", None),
        ("not_run", None),
        ("unknown", None),
        (None, None),
    ],
)
def test_production_scorers_map_exported_statuses(scorer, metadata_key, status, expected):
    metadata = {} if status is None else {metadata_key: status}

    assert scorer(metadata=metadata) is expected
