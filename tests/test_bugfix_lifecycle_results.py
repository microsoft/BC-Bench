from bcbench.results import bugfix as bugfix_results
from tests.conftest import create_bugfix_result


def test_checkpointed_full_success_passes_all_metrics() -> None:
    passed = bugfix_results.BugFixPhaseResult(status=bugfix_results.BugFixPhaseStatus.PASSED)

    result = create_bugfix_result(
        runtime_isolation="database-checkpointed-single-container",
        test_red=passed,
        test_gold=passed,
        fix_build=passed,
        generated_pair=passed,
        benchmark_fix=passed,
    )

    assert result.metric_status(bugfix_results.BugFixMetricName.GENERATED_TEST_VALIDITY) is bugfix_results.BugFixPhaseStatus.PASSED
    assert result.metric_status(bugfix_results.BugFixMetricName.GENERATED_PAIR_TRANSITION) is bugfix_results.BugFixPhaseStatus.PASSED
    assert result.metric_status(bugfix_results.BugFixMetricName.FIX_BUILD) is bugfix_results.BugFixPhaseStatus.PASSED
    assert result.metric_status(bugfix_results.BugFixMetricName.FIX_QUALITY) is bugfix_results.BugFixPhaseStatus.PASSED
    assert result.metric_status(bugfix_results.BugFixMetricName.RESOLUTION) is bugfix_results.BugFixPhaseStatus.PASSED
    assert result.generated_test_pre_patch_failed is True
    assert result.generated_test_post_patch_passed is True
    assert result.build is True
    assert result.benchmark_test_passed is True
    assert result.resolved is True


def test_invalid_generated_test_preserves_successful_fix_quality() -> None:
    invalid = bugfix_results.BugFixPhaseResult(status=bugfix_results.BugFixPhaseStatus.INVALID_SUBMISSION)
    passed = bugfix_results.BugFixPhaseResult(status=bugfix_results.BugFixPhaseStatus.PASSED)

    result = create_bugfix_result(
        runtime_isolation="database-checkpointed-single-container",
        test_red=invalid,
        test_gold=passed,
        fix_build=passed,
        generated_pair=passed,
        benchmark_fix=passed,
    )

    assert result.metric_status(bugfix_results.BugFixMetricName.GENERATED_TEST_VALIDITY) is bugfix_results.BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.metric_status(bugfix_results.BugFixMetricName.FIX_QUALITY) is bugfix_results.BugFixPhaseStatus.PASSED
    assert result.metric_status(bugfix_results.BugFixMetricName.RESOLUTION) is bugfix_results.BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.benchmark_test_passed is True
    assert result.resolved is False


def test_failed_required_phase_precedes_infrastructure_error() -> None:
    failed = bugfix_results.BugFixPhaseResult(status=bugfix_results.BugFixPhaseStatus.FAILED)
    infrastructure_error = bugfix_results.BugFixPhaseResult(status=bugfix_results.BugFixPhaseStatus.INFRASTRUCTURE_ERROR)
    passed = bugfix_results.BugFixPhaseResult(status=bugfix_results.BugFixPhaseStatus.PASSED)

    result = create_bugfix_result(
        runtime_isolation="database-checkpointed-single-container",
        test_red=failed,
        test_gold=passed,
        fix_build=passed,
        generated_pair=passed,
        benchmark_fix=infrastructure_error,
    )

    assert result.metric_status(bugfix_results.BugFixMetricName.RESOLUTION) is bugfix_results.BugFixPhaseStatus.FAILED


def test_timeout_only_forces_resolution_to_failed() -> None:
    passed = bugfix_results.BugFixPhaseResult(status=bugfix_results.BugFixPhaseStatus.PASSED)

    result = create_bugfix_result(
        runtime_isolation="database-checkpointed-single-container",
        timeout=True,
        test_red=passed,
        test_gold=passed,
        fix_build=passed,
        generated_pair=passed,
        benchmark_fix=passed,
    )

    assert result.metric_status(bugfix_results.BugFixMetricName.FIX_QUALITY) is bugfix_results.BugFixPhaseStatus.PASSED
    assert result.metric_status(bugfix_results.BugFixMetricName.RESOLUTION) is bugfix_results.BugFixPhaseStatus.FAILED
    assert result.benchmark_test_passed is True
    assert result.resolved is False


def test_package_normalized_metrics_map_legacy_fields() -> None:
    result = create_bugfix_result(
        build=False,
        benchmark_test_passed=True,
        resolved=False,
    )

    assert result.metric_status(bugfix_results.BugFixMetricName.GENERATED_TEST_VALIDITY) is bugfix_results.BugFixPhaseStatus.NOT_RUN
    assert result.metric_status(bugfix_results.BugFixMetricName.GENERATED_PAIR_TRANSITION) is bugfix_results.BugFixPhaseStatus.NOT_RUN
    assert result.metric_status(bugfix_results.BugFixMetricName.FIX_BUILD) is bugfix_results.BugFixPhaseStatus.FAILED
    assert result.metric_status(bugfix_results.BugFixMetricName.FIX_QUALITY) is bugfix_results.BugFixPhaseStatus.PASSED
    assert result.metric_status(bugfix_results.BugFixMetricName.RESOLUTION) is bugfix_results.BugFixPhaseStatus.FAILED
