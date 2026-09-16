from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from bcbench.results.base import BaseEvaluationResult, ExecutionBasedEvaluationResult
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory, EvaluationContext


class BugFixPhaseStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INVALID_SUBMISSION = "invalid_submission"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    NOT_RUN = "not_run"


class BugFixMetricName(StrEnum):
    GENERATED_TEST_VALIDITY = "GeneratedTestValidity"
    GENERATED_PAIR_TRANSITION = "GeneratedPairTransition"
    FIX_BUILD = "FixBuild"
    FIX_QUALITY = "FixQuality"
    RESOLUTION = "Resolution"


class BugFixMetricSummary(BaseModel):
    successes: int
    determined_failures: int
    unknown: int
    scheduled: int
    rate: float | None
    coverage: float

    @classmethod
    def from_statuses(cls, statuses: Sequence[BugFixPhaseStatus]) -> "BugFixMetricSummary":
        successes = statuses.count(BugFixPhaseStatus.PASSED)
        determined_failures = sum(statuses.count(status) for status in (BugFixPhaseStatus.FAILED, BugFixPhaseStatus.INVALID_SUBMISSION))
        unknown = sum(statuses.count(status) for status in (BugFixPhaseStatus.INFRASTRUCTURE_ERROR, BugFixPhaseStatus.NOT_RUN))
        scheduled = len(statuses)
        return cls._from_counts(successes, determined_failures, unknown, scheduled)

    @classmethod
    def _from_counts(cls, successes: int, determined_failures: int, unknown: int, scheduled: int) -> "BugFixMetricSummary":
        determined = successes + determined_failures
        return cls(
            successes=successes,
            determined_failures=determined_failures,
            unknown=unknown,
            scheduled=scheduled,
            rate=successes / determined if determined else None,
            coverage=determined / scheduled if scheduled else 0.0,
        )


class BugFixPhaseResult(BaseModel):
    status: BugFixPhaseStatus = BugFixPhaseStatus.NOT_RUN
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    source_hash: str | None = None
    checkpoint_hash: str | None = None
    requested_tests: tuple[str, ...] = ()
    discovered_tests: tuple[str, ...] = ()
    executed_tests: tuple[str, ...] = ()
    evidence: dict[str, str] = Field(default_factory=dict)


RuntimeIsolation = Literal["package-normalized", "database-checkpointed-single-container"]


def _combine_required_statuses(*statuses: BugFixPhaseStatus) -> BugFixPhaseStatus:
    for status in (
        BugFixPhaseStatus.INVALID_SUBMISSION,
        BugFixPhaseStatus.FAILED,
        BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
        BugFixPhaseStatus.NOT_RUN,
        BugFixPhaseStatus.PASSED,
    ):
        if status in statuses:
            return status
    return BugFixPhaseStatus.PASSED


class BugFixResult(ExecutionBasedEvaluationResult):
    """Result class for bug-fix evaluation category."""

    generated_test_pre_patch_failed: bool = False
    generated_test_post_patch_passed: bool = False
    benchmark_test_passed: bool = False
    runtime_isolation: RuntimeIsolation = "package-normalized"
    generated_fix_hash: str | None = None
    generated_test_hash: str | None = None
    baseline_checkpoint_hash: str | None = None
    fixed_checkpoint_hash: str | None = None
    test_red: BugFixPhaseResult = Field(default_factory=BugFixPhaseResult)
    test_gold: BugFixPhaseResult = Field(default_factory=BugFixPhaseResult)
    fix_build: BugFixPhaseResult = Field(default_factory=BugFixPhaseResult)
    generated_pair: BugFixPhaseResult = Field(default_factory=BugFixPhaseResult)
    benchmark_fix: BugFixPhaseResult = Field(default_factory=BugFixPhaseResult)

    def metric_status(self, metric: BugFixMetricName) -> BugFixPhaseStatus:
        if self.runtime_isolation == "package-normalized":
            if metric in (BugFixMetricName.GENERATED_TEST_VALIDITY, BugFixMetricName.GENERATED_PAIR_TRANSITION):
                return BugFixPhaseStatus.NOT_RUN
            if self.infrastructure_failure:
                return BugFixPhaseStatus.INFRASTRUCTURE_ERROR
            legacy_status = {
                BugFixMetricName.FIX_BUILD: self.build,
                BugFixMetricName.FIX_QUALITY: self.benchmark_test_passed,
                BugFixMetricName.RESOLUTION: self.resolved,
            }
            return BugFixPhaseStatus.PASSED if legacy_status[metric] else BugFixPhaseStatus.FAILED

        if metric is BugFixMetricName.GENERATED_TEST_VALIDITY:
            return _combine_required_statuses(self.test_red.status, self.test_gold.status)
        if metric is BugFixMetricName.GENERATED_PAIR_TRANSITION:
            return _combine_required_statuses(self.test_red.status, self.generated_pair.status)
        if metric is BugFixMetricName.FIX_BUILD:
            return self.fix_build.status
        if metric is BugFixMetricName.FIX_QUALITY:
            return self.benchmark_fix.status
        if self.timeout:
            return BugFixPhaseStatus.FAILED
        return _combine_required_statuses(
            self.metric_status(BugFixMetricName.GENERATED_TEST_VALIDITY),
            self.metric_status(BugFixMetricName.GENERATED_PAIR_TRANSITION),
            self.metric_status(BugFixMetricName.FIX_QUALITY),
        )

    @property
    def category_metrics(self) -> dict[str, int | float | bool | str]:
        return {
            **super().category_metrics,
            "generated_test_pre_patch_failed": self.generated_test_pre_patch_failed,
            "generated_test_post_patch_passed": self.generated_test_post_patch_passed,
            "benchmark_test_passed": self.benchmark_test_passed,
            "generated_test_validity_status": self.metric_status(BugFixMetricName.GENERATED_TEST_VALIDITY).value,
            "generated_pair_transition_status": self.metric_status(BugFixMetricName.GENERATED_PAIR_TRANSITION).value,
            "fix_build_status": self.metric_status(BugFixMetricName.FIX_BUILD).value,
            "fix_quality_status": self.metric_status(BugFixMetricName.FIX_QUALITY).value,
            "resolution_status": self.metric_status(BugFixMetricName.RESOLUTION).value,
            "runtime_isolation": self.runtime_isolation,
        }

    @property
    def display_row(self) -> dict[str, str]:
        return {
            "Generated Test Failed Before Fix": "Yes" if self.generated_test_pre_patch_failed else "No",
            "Generated Test Passed After Fix": "Yes" if self.generated_test_post_patch_passed else "No",
            "Benchmark Test Passed": "Yes" if self.benchmark_test_passed else "No",
        }

    @classmethod
    def create_success(cls, context: "EvaluationContext", output: str) -> Self:
        return cls(
            **cls._base_fields(context),
            output=output,
            resolved=True,
            build=True,
            generated_test_pre_patch_failed=True,
            generated_test_post_patch_passed=True,
            benchmark_test_passed=True,
        )

    @classmethod
    def create_verification_failure(
        cls,
        context: "EvaluationContext",
        output: str,
        error_message: str,
        *,
        build: bool,
        infrastructure_failure: bool = False,
        generated_test_pre_patch_failed: bool = False,
        generated_test_post_patch_passed: bool = False,
    ) -> Self:
        return cls(
            **cls._base_fields(context),
            output=output,
            error_message=error_message,
            resolved=False,
            build=build,
            infrastructure_failure=infrastructure_failure,
            generated_test_pre_patch_failed=generated_test_pre_patch_failed,
            generated_test_post_patch_passed=generated_test_post_patch_passed,
            benchmark_test_passed=False,
        )

    @classmethod
    def create_test_infrastructure_failure(
        cls,
        context: "EvaluationContext",
        output: str,
        error_message: str,
        *,
        generated_test_pre_patch_failed: bool = False,
        generated_test_post_patch_passed: bool = False,
    ) -> Self:
        return cls.create_verification_failure(
            context,
            output,
            error_message,
            build=True,
            infrastructure_failure=True,
            generated_test_pre_patch_failed=generated_test_pre_patch_failed,
            generated_test_post_patch_passed=generated_test_post_patch_passed,
        )

    @classmethod
    def create_test_failure(cls, context: "EvaluationContext", output: str, error_message: str = "Tests failed") -> Self:
        return cls.create_verification_failure(context, output, error_message, build=True)


def _empty_metric_summaries() -> dict[BugFixMetricName, BugFixMetricSummary]:
    return {metric: BugFixMetricSummary.from_statuses(()) for metric in BugFixMetricName}


class BugFixResultSummary(ExecutionBasedEvaluationResultSummary):
    runtime_isolation: RuntimeIsolation = "package-normalized"
    metric_summaries: dict[BugFixMetricName, BugFixMetricSummary] = Field(default_factory=_empty_metric_summaries)

    @model_validator(mode="before")
    @classmethod
    def restore_legacy_metric_summaries(cls, payload: object) -> object:
        if not isinstance(payload, dict) or "metric_summaries" in payload:
            return payload

        data: dict[str, Any] = dict(payload)
        if data.get("runtime_isolation", "package-normalized") != "package-normalized":
            return payload

        total = int(data["total"])
        resolved = int(data.get("resolved", 0))
        failed = int(data.get("failed", 0))
        infrastructure_failed = int(data.get("infrastructure_failed", 0))
        build = int(data.get("build", 0))

        resolution_unknown = total - resolved - failed
        fix_build_failures = total - infrastructure_failed - build
        if resolution_unknown < 0 or fix_build_failures < 0:
            raise ValueError("Legacy bug-fix summary counts cannot exceed total")

        data["metric_summaries"] = {
            BugFixMetricName.GENERATED_TEST_VALIDITY: BugFixMetricSummary._from_counts(0, 0, total, total),
            BugFixMetricName.GENERATED_PAIR_TRANSITION: BugFixMetricSummary._from_counts(0, 0, total, total),
            BugFixMetricName.FIX_BUILD: BugFixMetricSummary._from_counts(
                build,
                fix_build_failures,
                infrastructure_failed,
                total,
            ),
            BugFixMetricName.FIX_QUALITY: BugFixMetricSummary._from_counts(0, 0, total, total),
            BugFixMetricName.RESOLUTION: BugFixMetricSummary._from_counts(
                resolved,
                failed,
                resolution_unknown,
                total,
            ),
        }
        return data

    @classmethod
    def from_results(cls, results: Sequence[BaseEvaluationResult], run_id: str) -> "BugFixResultSummary":
        if not results:
            raise ValueError("Cannot summarize an empty bug-fix results list")

        non_bugfix_results = [result for result in results if not isinstance(result, BugFixResult)]
        if non_bugfix_results:
            result_types = sorted({type(result).__name__ for result in non_bugfix_results})
            raise ValueError(f"BugFixResultSummary requires only BugFixResult instances, got: {result_types}")

        bugfix_results = [result for result in results if isinstance(result, BugFixResult)]
        categories = {result.category for result in bugfix_results}
        if len(categories) != 1:
            raise ValueError(f"Cannot summarize bug-fix results with mixed categories: {categories}")
        if categories != {EvaluationCategory.BUG_FIX}:
            raise ValueError(f"BugFixResultSummary requires the bug-fix category, got: {categories}")

        runtime_isolations = {result.runtime_isolation for result in bugfix_results}
        if len(runtime_isolations) != 1:
            raise ValueError(f"Cannot summarize bug-fix results with mixed runtime isolation: {runtime_isolations}")

        summary = super().from_results(results, run_id)
        assert isinstance(summary, BugFixResultSummary)

        runtime_isolation = runtime_isolations.pop()
        metric_summaries = {metric: BugFixMetricSummary.from_statuses([result.metric_status(metric) for result in bugfix_results]) for metric in BugFixMetricName}
        resolution_statuses = {result.instance_id: result.metric_status(BugFixMetricName.RESOLUTION) for result in bugfix_results}
        resolution = metric_summaries[BugFixMetricName.RESOLUTION]
        fix_build = metric_summaries[BugFixMetricName.FIX_BUILD]
        instance_results = {
            instance_id: status is BugFixPhaseStatus.PASSED
            for instance_id, status in resolution_statuses.items()
            if status in (BugFixPhaseStatus.PASSED, BugFixPhaseStatus.FAILED, BugFixPhaseStatus.INVALID_SUBMISSION)
        }
        return summary.model_copy(
            update={
                "resolved": resolution.successes,
                "failed": resolution.determined_failures,
                "build": fix_build.successes,
                "percentage": round(resolution.rate * 100, 1) if resolution.rate is not None else None,
                "instance_results": instance_results,
                "runtime_isolation": runtime_isolation,
                "metric_summaries": metric_summaries,
            }
        )

    def render_github_metrics_markdown(self) -> str:
        labels = {
            BugFixMetricName.GENERATED_TEST_VALIDITY: "Generated Test Validity",
            BugFixMetricName.GENERATED_PAIR_TRANSITION: "Generated Pair Transition",
            BugFixMetricName.FIX_BUILD: "Fix Build",
            BugFixMetricName.FIX_QUALITY: "Fix Quality",
            BugFixMetricName.RESOLUTION: "Resolution",
        }
        production_metrics = ["\n## Production Metrics\n"]
        for metric in BugFixMetricName:
            metric_summary = self.metric_summaries[metric]
            rate = f"{metric_summary.rate * 100:.1f}%" if metric_summary.rate is not None else "N/A"
            determined = metric_summary.successes + metric_summary.determined_failures
            production_metrics.append(f"- {labels[metric]}: {rate} (coverage {metric_summary.coverage * 100:.1f}%, {determined}/{metric_summary.scheduled} determined)\n")
        return super().render_github_metrics_markdown() + "".join(production_metrics)

    def combination_key(self) -> tuple[str | None, ...]:
        return (*super().combination_key(), self.runtime_isolation)
