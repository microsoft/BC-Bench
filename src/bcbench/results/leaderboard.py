import logging
from abc import ABC
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, override

from bcbench_core.scoring import pass_hat_k
from bcbench_core.stats import bootstrap_ci
from pydantic import BaseModel

from bcbench.results.summary import EvaluationResultSummary, ExecutionBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory, ExperimentConfiguration

logger = logging.getLogger(__name__)


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

        cls._validate_consistent_runs(runs)
        return cls(**cls._base_fields(runs))


class ExecutionBasedLeaderboardAggregate(LeaderboardAggregate):
    """Aggregate for execution-based categories: resolution-rate average with bootstrap CI and pass^5."""

    average: float = 0.0
    ci_low: float | None = None
    ci_high: float | None = None
    pass_hat_5: float | None = None

    @classmethod
    @override
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


class JudgeBasedLeaderboardAggregate(LeaderboardAggregate):
    """Aggregate for judge-scored categories."""

    judge_model: str

    @classmethod
    @override
    def _base_fields(cls, runs: Sequence[EvaluationResultSummary]) -> dict[str, Any]:
        from bcbench.results.summary import JudgeBasedEvaluationResultSummary

        first_run = runs[0]
        assert isinstance(first_run, JudgeBasedEvaluationResultSummary)
        return {**super()._base_fields(runs), "judge_model": first_run.judge_model}


class Leaderboard(BaseModel):
    """Leaderboard holding per-run summaries and their multi-run aggregates for a category."""

    runs: list[EvaluationResultSummary]
    aggregate: list[LeaderboardAggregate]

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
