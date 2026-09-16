import json
from abc import ABC
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from bcbench.logger import get_logger
from bcbench.results.bugfix import BugFixMetricName, BugFixResultSummary, RuntimeIsolation
from bcbench.results.metrics import bootstrap_ci, pass_hat_k
from bcbench.results.summary import EvaluationResultSummary, ExecutionBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory, ExperimentConfiguration

logger = get_logger(__name__)


class LeaderboardAggregate(BaseModel, ABC):
    """Aggregate metrics across multiple runs of the same combination.

    EvaluationResultSummary holds the result of one run, while LeaderboardAggregate holds the results of many runs of the same combination.

    The base carries only identity and run-shape fields. Each category subclass declares and computes its own headline metric (and any spread/extra metrics), because the underlying distributions differ (e.g. resolution-rate booleans vs F1 ratios).
    """

    model: str
    agent_name: str
    category: EvaluationCategory
    agent_version: str | None = None
    experiment: ExperimentConfiguration | None = None

    total: int
    num_runs: int

    average_duration: float

    benchmark_version: str

    @staticmethod
    def _validate_consistent_runs(runs: Sequence[EvaluationResultSummary]) -> None:
        keys = {run.combination_key() for run in runs}
        if len(keys) > 1:
            raise ValueError(f"Cannot aggregate runs from different combinations: {keys}")

        totals = {run.total for run in runs}
        if len(totals) > 1:
            raise ValueError(f"Cannot aggregate runs with different totals: {totals}")

    @classmethod
    def _base_fields(cls, runs: Sequence[EvaluationResultSummary]) -> dict[str, Any]:
        first_run: EvaluationResultSummary = runs[0]
        durations: list[float] = [r.average_duration for r in runs if r.average_duration]

        return {
            "model": first_run.model,
            "agent_name": first_run.agent_name,
            "agent_version": first_run.agent_version,
            "category": first_run.category,
            "experiment": first_run.experiment,
            "total": first_run.total,
            "num_runs": len(runs),
            "average_duration": sum(durations) / len(durations) if durations else 0.0,
            "benchmark_version": first_run.benchmark_version,
        }

    @classmethod
    def from_runs(cls, runs: Sequence[EvaluationResultSummary]) -> "LeaderboardAggregate":
        """Create an aggregate from multiple runs of the same combination."""
        if not runs:
            raise ValueError("Cannot create aggregate from empty runs list")

        if cls is LeaderboardAggregate:
            return runs[0].category.aggregate_class.from_runs(runs)

        cls._validate_consistent_runs(runs)
        return cls(**cls._base_fields(runs))

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "LeaderboardAggregate":
        category = EvaluationCategory(payload["category"])
        return category.aggregate_class.model_validate(payload)


class ExecutionBasedLeaderboardAggregate(LeaderboardAggregate):
    """Aggregate for execution-based categories: resolution-rate average with bootstrap CI and pass^5."""

    average: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    pass_hat_5: float | None = None

    @classmethod
    def from_runs(cls, runs: Sequence[EvaluationResultSummary]) -> "ExecutionBasedLeaderboardAggregate":
        base = super().from_runs(runs)
        assert isinstance(base, ExecutionBasedLeaderboardAggregate)

        execution_runs: list[ExecutionBasedEvaluationResultSummary] = [r for r in runs if isinstance(r, ExecutionBasedEvaluationResultSummary)]

        per_run_resolution_rates: list[float] = [run.resolved / evaluated for run in execution_runs if (evaluated := run.resolved + run.failed) > 0]

        instance_resolved: dict[str, list[bool]] = defaultdict(list)
        for run in execution_runs:
            for instance_id, outcome in run.instance_results.items():
                instance_resolved[instance_id].append(outcome)

        pass_hat_5 = _calculate_pass_hat_k(instance_resolved, 5)

        ci = bootstrap_ci(per_run_resolution_rates)
        return base.model_copy(
            update={
                "average": round(ci["mean"], 3) if per_run_resolution_rates and ci["mean"] is not None else None,
                "ci_low": round(ci["ci_low"], 3) if ci["ci_low"] is not None else None,
                "ci_high": round(ci["ci_high"], 3) if ci["ci_high"] is not None else None,
                "pass_hat_5": pass_hat_5,
            }
        )


def _empty_bugfix_metric_averages() -> dict[str, float | None]:
    return {metric.value: None for metric in BugFixMetricName}


def _empty_bugfix_metric_coverages() -> dict[str, float]:
    return {metric.value: 0.0 for metric in BugFixMetricName}


class BugFixLeaderboardAggregate(ExecutionBasedLeaderboardAggregate):
    runtime_isolation: RuntimeIsolation = "package-normalized"
    metric_averages: dict[str, float | None] = Field(default_factory=_empty_bugfix_metric_averages)
    metric_coverages: dict[str, float] = Field(default_factory=_empty_bugfix_metric_coverages)

    @model_validator(mode="after")
    def validate_metric_maps(self) -> "BugFixLeaderboardAggregate":
        expected_metrics = {metric.value for metric in BugFixMetricName}
        metric_maps = {
            "metric_averages": self.metric_averages,
            "metric_coverages": self.metric_coverages,
        }
        for field, values in metric_maps.items():
            actual_metrics = set(values)
            if actual_metrics != expected_metrics:
                missing = sorted(expected_metrics - actual_metrics)
                extra = sorted(actual_metrics - expected_metrics)
                raise ValueError(f"{field} must contain exactly every BugFixMetricName; missing={missing}, extra={extra}")

        for value in self.metric_averages.values():
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError("metric_averages values must be None or within [0, 1]")
        if any(not 0.0 <= value <= 1.0 for value in self.metric_coverages.values()):
            raise ValueError("metric_coverages values must be within [0, 1]")

        resolution_average = self.metric_averages[BugFixMetricName.RESOLUTION]
        if self.average is not None and resolution_average is not None and round(self.average, 3) != round(resolution_average, 3):
            raise ValueError("average must agree with metric_averages[Resolution] after rounding to 3 decimals")
        return self

    @classmethod
    def from_runs(cls, runs: Sequence[EvaluationResultSummary]) -> "BugFixLeaderboardAggregate":
        base = super().from_runs(runs)
        assert isinstance(base, BugFixLeaderboardAggregate)

        bugfix_runs = [run for run in runs if isinstance(run, BugFixResultSummary)]
        if not bugfix_runs:
            return base

        first_run = bugfix_runs[0]
        metric_averages: dict[str, float | None] = {}
        metric_coverages: dict[str, float] = {}
        for metric in BugFixMetricName:
            rates = [summary.rate for run in bugfix_runs if (summary := run.metric_summaries[metric]).rate is not None]
            coverages = [run.metric_summaries[metric].coverage for run in bugfix_runs]
            metric_averages[metric.value] = sum(rates) / len(rates) if rates else None
            metric_coverages[metric.value] = sum(coverages) / len(coverages)

        return cls.model_validate(
            {
                **base.model_dump(),
                "runtime_isolation": first_run.runtime_isolation,
                "metric_averages": metric_averages,
                "metric_coverages": metric_coverages,
            }
        )


class JudgeBasedLeaderboardAggregate(LeaderboardAggregate):
    """Aggregate for judge-scored categories."""

    judge_model: str

    @classmethod
    def _base_fields(cls, runs: Sequence[EvaluationResultSummary]) -> dict[str, Any]:
        from bcbench.results.summary import JudgeBasedEvaluationResultSummary

        first_run = runs[0]
        assert isinstance(first_run, JudgeBasedEvaluationResultSummary)
        return {**super()._base_fields(runs), "judge_model": first_run.judge_model}


class CodeReviewLeaderboardAggregate(JudgeBasedLeaderboardAggregate):
    """Aggregate for the code-review category: mean F1 across runs with bootstrap CI."""

    f1: float = 0.0
    f1_ci_low: float | None = None
    f1_ci_high: float | None = None
    f_beta_05: float = 0.0
    f_beta_2: float = 0.0
    precision: float = 0.0
    recall: float = 0.0

    macro_f1: float = 0.0
    macro_f1_ci_low: float | None = None
    macro_f1_ci_high: float | None = None
    macro_f_beta_05: float = 0.0
    macro_f_beta_2: float = 0.0
    macro_precision: float = 0.0
    macro_recall: float = 0.0

    valid_review_output_rate: float = 0.0
    average_prompt_tokens: float | None = None
    average_completion_tokens: float | None = None
    average_total_tokens: float | None = None
    average_ai_credits: float | None = None

    @classmethod
    def from_runs(cls, runs: Sequence[EvaluationResultSummary]) -> "CodeReviewLeaderboardAggregate":
        from bcbench.results.codereview import CodeReviewResultSummary

        base = super().from_runs(runs)
        assert isinstance(base, CodeReviewLeaderboardAggregate)

        cr_runs: list[CodeReviewResultSummary] = [run for run in runs if isinstance(run, CodeReviewResultSummary)]
        n = len(cr_runs)

        def mean_metric(values: Sequence[float | None]) -> float | None:
            available = [value for value in values if value is not None]
            return sum(available) / len(available) if available else None

        # The micro headline pools every comment across the dataset, so there is no per-task
        # decomposition to resample; its CI is intentionally over run-level means and captures
        # run-to-run reproducibility (None unless >=2 runs with variance).
        f1_ci = bootstrap_ci([r.f1 for r in cr_runs])
        # The macro headline weights tasks equally, so we bootstrap the equal-weight headline over the
        # pooled per-task F1 scores across runs: the CI reflects task-level variance (resampling tasks),
        # which is the dominant sampling uncertainty for our small task set and is meaningful even for a
        # single run. This deliberately differs from the per-run micro CI above.
        pooled_task_f1 = [score for r in cr_runs for score in r.instance_results.values()]
        macro_f1_ci = bootstrap_ci(pooled_task_f1)

        return base.model_copy(
            update={
                "f1": round(f1_ci["mean"], 3) if f1_ci["mean"] is not None else 0.0,
                "f1_ci_low": round(f1_ci["ci_low"], 3) if f1_ci["ci_low"] is not None else None,
                "f1_ci_high": round(f1_ci["ci_high"], 3) if f1_ci["ci_high"] is not None else None,
                "f_beta_05": sum(r.f_beta_05 for r in cr_runs) / n,
                "f_beta_2": sum(r.f_beta_2 for r in cr_runs) / n,
                "precision": sum(r.precision for r in cr_runs) / n,
                "recall": sum(r.recall for r in cr_runs) / n,
                "macro_f1": round(macro_f1_ci["mean"], 3) if macro_f1_ci["mean"] is not None else 0.0,
                "macro_f1_ci_low": round(macro_f1_ci["ci_low"], 3) if macro_f1_ci["ci_low"] is not None else None,
                "macro_f1_ci_high": round(macro_f1_ci["ci_high"], 3) if macro_f1_ci["ci_high"] is not None else None,
                "macro_f_beta_05": sum(r.macro_f_beta_05 for r in cr_runs) / n,
                "macro_f_beta_2": sum(r.macro_f_beta_2 for r in cr_runs) / n,
                "macro_precision": sum(r.macro_precision for r in cr_runs) / n,
                "macro_recall": sum(r.macro_recall for r in cr_runs) / n,
                "valid_review_output_rate": sum(r.valid_review_output_rate for r in cr_runs) / n,
                "average_prompt_tokens": mean_metric([run.average_prompt_tokens for run in cr_runs]),
                "average_completion_tokens": mean_metric([run.average_completion_tokens for run in cr_runs]),
                "average_total_tokens": mean_metric([run.average_total_tokens for run in cr_runs]),
                "average_ai_credits": mean_metric([run.average_ai_credits for run in cr_runs]),
            }
        )


class Leaderboard(BaseModel):
    """Leaderboard holding per-run summaries and their multi-run aggregates for a category.

    Runs and aggregates are deserialized into the correct category-specific subclasses via
    their respective from_json dispatchers.
    """

    runs: list[EvaluationResultSummary]
    aggregate: list[LeaderboardAggregate]

    @model_validator(mode="before")
    @classmethod
    def _rebuild_legacy_bugfix_aggregates(cls, payload: object) -> object:
        if not isinstance(payload, dict):
            return payload

        raw_runs = payload.get("runs")
        raw_aggregates = payload.get("aggregate")
        if not isinstance(raw_runs, list) or not isinstance(raw_aggregates, list):
            return payload

        runs = [EvaluationResultSummary.from_json(item) if isinstance(item, dict) else item for item in raw_runs]
        aggregates: list[dict[str, Any] | LeaderboardAggregate] = []
        rebuilt = False
        for item in raw_aggregates:
            is_legacy_bugfix = isinstance(item, dict) and item.get("category") == EvaluationCategory.BUG_FIX and ("metric_averages" not in item or "metric_coverages" not in item)
            if not is_legacy_bugfix:
                aggregates.append(item)
                continue

            legacy_aggregate = BugFixLeaderboardAggregate.model_validate(item)
            aggregate_key = _bugfix_aggregate_combination_key(legacy_aggregate)
            matching_runs = [run for run in runs if isinstance(run, BugFixResultSummary) and run.combination_key() == aggregate_key]
            if not matching_runs:
                raise ValueError(f"Cannot rebuild legacy bug-fix aggregate without matching runs: {aggregate_key}")

            aggregates.append(BugFixLeaderboardAggregate.from_runs(matching_runs))
            rebuilt = True

        if not rebuilt:
            return payload
        return {**payload, "runs": runs, "aggregate": aggregates}

    @field_validator("runs", mode="before")
    @classmethod
    def _deserialize_runs(cls, value: list[dict[str, Any] | EvaluationResultSummary]) -> list[EvaluationResultSummary]:
        return [EvaluationResultSummary.from_json(item) if isinstance(item, dict) else item for item in value]

    @field_validator("aggregate", mode="before")
    @classmethod
    def _deserialize_aggregate(cls, value: list[dict[str, Any] | LeaderboardAggregate]) -> list[LeaderboardAggregate]:
        return [LeaderboardAggregate.from_json(item) if isinstance(item, dict) else item for item in value]

    @classmethod
    def load(cls, path: Path) -> "Leaderboard":
        if not path.exists():
            return cls(runs=[], aggregate=[])
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
            if not data or not isinstance(data, dict):
                return cls(runs=[], aggregate=[])
            return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs": [r.to_dict() for r in self.runs],
            "aggregate": [a.model_dump(mode="json") for a in self.aggregate],
        }


def _calculate_pass_hat_k(instance_resolved: dict[str, list[bool]], k: int) -> float | None:
    instance_pass_hat_k = [pass_hat_k(len(results), sum(results), k) for results in instance_resolved.values() if len(results) >= k]
    return round(sum(instance_pass_hat_k) / len(instance_pass_hat_k), 3) if instance_pass_hat_k else None


def _bugfix_aggregate_combination_key(aggregate: BugFixLeaderboardAggregate) -> tuple[str | None, ...]:
    experiment_key: str | None = None
    if aggregate.experiment and not aggregate.experiment.is_empty():
        experiment_key = json.dumps(aggregate.experiment.model_dump(mode="json"), sort_keys=True)
    return (
        aggregate.agent_name,
        aggregate.agent_version,
        aggregate.model,
        experiment_key,
        aggregate.benchmark_version,
        aggregate.runtime_isolation,
    )
