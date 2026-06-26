import json
from abc import ABC
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator

from bcbench.logger import get_logger
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

    average: float = 0.0
    ci_low: float | None = None
    ci_high: float | None = None
    pass_hat_5: float | None = None

    @classmethod
    def from_runs(cls, runs: Sequence[EvaluationResultSummary]) -> "ExecutionBasedLeaderboardAggregate":
        base = super().from_runs(runs)
        assert isinstance(base, ExecutionBasedLeaderboardAggregate)

        execution_runs: list[ExecutionBasedEvaluationResultSummary] = [r for r in runs if isinstance(r, ExecutionBasedEvaluationResultSummary)]

        per_run_resolution_rates: list[float] = [run.resolved / run.total for run in execution_runs if run.total > 0]

        instance_resolved: dict[str, list[bool]] = defaultdict(list)
        for run in execution_runs:
            for instance_id, outcome in run.instance_results.items():
                instance_resolved[instance_id].append(outcome)

        pass_hat_5: float | None = _calculate_pass_hat_k(instance_resolved, 5, base.num_runs) if base.num_runs >= 5 else None

        ci = bootstrap_ci(per_run_resolution_rates)
        return base.model_copy(
            update={
                "average": round(ci["mean"], 3) if ci["mean"] is not None else 0.0,
                "ci_low": round(ci["ci_low"], 3) if ci["ci_low"] is not None else None,
                "ci_high": round(ci["ci_high"], 3) if ci["ci_high"] is not None else None,
                "pass_hat_5": pass_hat_5,
            }
        )


class CodeReviewLeaderboardAggregate(LeaderboardAggregate):
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

    @classmethod
    def from_runs(cls, runs: Sequence[EvaluationResultSummary]) -> "CodeReviewLeaderboardAggregate":
        from bcbench.results.codereview import CodeReviewResultSummary

        base = super().from_runs(runs)
        assert isinstance(base, CodeReviewLeaderboardAggregate)

        cr_runs: list[CodeReviewResultSummary] = [run for run in runs if isinstance(run, CodeReviewResultSummary)]
        n = len(cr_runs)

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
            }
        )


class JudgeBasedLeaderboardAggregate(LeaderboardAggregate):
    """Aggregate for judge-scored categories.

    Headline scoring is performed externally (bceval -> Braintrust/Kusto), so only the
    identity and run-shape fields from the base class are aggregated here.
    """


class Leaderboard(BaseModel):
    """Leaderboard holding per-run summaries and their multi-run aggregates for a category.

    Runs and aggregates are deserialized into the correct category-specific subclasses via
    their respective from_json dispatchers.
    """

    runs: list[EvaluationResultSummary]
    aggregate: list[LeaderboardAggregate]

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
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            if not data or not isinstance(data, dict):
                return cls(runs=[], aggregate=[])
            return cls.model_validate(data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs": [r.to_dict() for r in self.runs],
            "aggregate": [a.model_dump(mode="json") for a in self.aggregate],
        }


def _calculate_pass_hat_k(instance_resolved: dict[str, list[bool]], k: int, num_trials: int) -> float:
    if num_trials < k:
        return 0.0

    total_pass_hat_k: float = 0.0
    for results in instance_resolved.values():
        success_count = sum(results[:num_trials])
        total_pass_hat_k += pass_hat_k(num_trials, success_count, k)

    return round(total_pass_hat_k / len(instance_resolved), 3)
