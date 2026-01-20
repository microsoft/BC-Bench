import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel

from bcbench.logger import get_logger
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.metrics import pass_hat_k
from bcbench.types import EvaluationCategory, ExperimentConfiguration

logger = get_logger(__name__)


class EvaluationResultSummary(BaseModel):
    total: int
    resolved: int
    failed: int
    build: int
    percentage: float

    date: date

    model: str
    agent_name: str
    category: EvaluationCategory

    average_duration: float
    average_prompt_tokens: float
    average_completion_tokens: float
    average_llm_duration: float | None = None
    average_tool_usage: dict[str, float] | None = None

    github_run_id: str | None = None
    experiment: ExperimentConfiguration | None = None

    # Per-instance results for aggregate metrics calculation: instance_id -> resolved
    instance_results: dict[str, bool] | None = None

    @classmethod
    def from_results(cls, results: Sequence[BaseEvaluationResult], run_id: str) -> "EvaluationResultSummary":
        total = len(results)
        resolved = sum(r.resolved for r in results)

        durations = [r.metrics.execution_time for r in results if r.metrics and r.metrics.execution_time is not None]
        prompt_tokens = [r.metrics.prompt_tokens for r in results if r.metrics and r.metrics.prompt_tokens is not None]
        completion_tokens = [r.metrics.completion_tokens for r in results if r.metrics and r.metrics.completion_tokens is not None]
        llm_durations = [r.metrics.llm_duration for r in results if r.metrics and r.metrics.llm_duration is not None]

        # Calculate average tool usage across all results
        tool_usages = [r.metrics.tool_usage for r in results if r.metrics and r.metrics.tool_usage is not None]
        average_tool_usage = _calculate_average_tool_usage(tool_usages) if tool_usages else None

        # Extract experiment configuration from first result (all should be same in a run)
        first_result = results[0]
        experiment = first_result.experiment if first_result.experiment and not first_result.experiment.is_empty() else None

        # Create per-instance results for aggregate metrics calculation
        instance_results = {r.instance_id: r.resolved for r in results}

        return cls(
            total=total,
            resolved=resolved,
            percentage=round(resolved / total * 100, 1),
            failed=total - resolved,
            build=sum(r.build for r in results),
            date=date.today(),
            category=first_result.category,
            model=first_result.model,
            agent_name=first_result.agent_name,
            average_duration=sum(durations) / len(durations) if durations else 0.0,
            average_prompt_tokens=sum(prompt_tokens) / len(prompt_tokens) if prompt_tokens else 0.0,
            average_completion_tokens=sum(completion_tokens) / len(completion_tokens) if completion_tokens else 0.0,
            average_llm_duration=sum(llm_durations) / len(llm_durations) if llm_durations else 0.0,
            average_tool_usage=average_tool_usage,
            github_run_id=run_id,
            experiment=experiment,
            instance_results=instance_results,
        )

    def to_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        # Round numeric values for readability
        data["average_duration"] = round(data["average_duration"], 1)
        data["average_prompt_tokens"] = round(data["average_prompt_tokens"], 1)
        data["average_completion_tokens"] = round(data["average_completion_tokens"], 1)
        return data

    def save(self, output_dir: Path, summary_file: str) -> None:
        output_file = output_dir / summary_file
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), indent=4))

        logger.info(f"Saved evaluation summary to {output_file}")


class LeaderboardAggregate(BaseModel):
    model: str
    agent_name: str
    category: EvaluationCategory
    experiment: ExperimentConfiguration | None = None

    # Total instances in benchmark
    total: int
    # Number of runs aggregated
    num_runs: int

    pass_hat_1: float | None = None
    pass_hat_3: float | None = None
    pass_hat_5: float | None = None

    # Averaged metrics across runs
    average_duration: float | None = None

    @classmethod
    def from_runs(cls, runs: Sequence[EvaluationResultSummary]) -> "LeaderboardAggregate":
        if not runs:
            raise ValueError("Cannot create aggregate from empty runs list")

        first_run: EvaluationResultSummary = runs[0]
        total: int = first_run.total
        num_runs: int = len(runs)

        # Warn if runs have different instance counts
        unique_totals = {r.total for r in runs}
        if len(unique_totals) > 1:
            logger.warning(f"Aggregating runs with different instance counts for '{first_run.agent_name}' + '{first_run.model}': {sorted(unique_totals)}. pass^k metrics may be misleading.")

        # Average duration across runs
        durations: list[float] = [r.average_duration for r in runs if r.average_duration]
        average_duration: float | None = sum(durations) / len(durations) if durations else None

        # Legacy single run without instance_results: use simple pass rate
        if num_runs == 1 and not first_run.instance_results:
            pass_rate = first_run.resolved / first_run.total if first_run.total > 0 else 0.0
            return cls(
                model=first_run.model,
                agent_name=first_run.agent_name,
                category=first_run.category,
                experiment=first_run.experiment,
                total=total,
                num_runs=num_runs,
                pass_hat_1=round(pass_rate, 3),
                pass_hat_3=None,
                pass_hat_5=None,
                average_duration=round(average_duration, 1) if average_duration else None,
            )

        # Multiple runs: all must have instance_results
        # Collect per-instance results across runs: instance_id -> list of resolved booleans
        instance_resolved: dict[str, list[bool]] = {}
        for run in runs:
            if run.instance_results:
                for instance_id, resolved in run.instance_results.items():
                    if instance_id not in instance_resolved:
                        instance_resolved[instance_id] = []
                    instance_resolved[instance_id].append(resolved)

        pass_hat_1 = _calculate_pass_hat_k(instance_resolved, 1, num_runs) if num_runs >= 1 else None
        pass_hat_3 = _calculate_pass_hat_k(instance_resolved, 3, num_runs) if num_runs >= 3 else None
        pass_hat_5 = _calculate_pass_hat_k(instance_resolved, 5, num_runs) if num_runs >= 5 else None

        return cls(
            model=first_run.model,
            agent_name=first_run.agent_name,
            category=first_run.category,
            experiment=first_run.experiment,
            total=total,
            num_runs=num_runs,
            pass_hat_1=pass_hat_1,
            pass_hat_3=pass_hat_3,
            pass_hat_5=pass_hat_5,
            average_duration=round(average_duration, 1) if average_duration else None,
        )


class Leaderboard(BaseModel):
    runs: list[EvaluationResultSummary]
    aggregate: list[LeaderboardAggregate]

    @classmethod
    def load(cls, path: Path) -> "Leaderboard":
        if not path.exists():
            return cls(runs=[], aggregate=[])
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            # Handle empty arrays or invalid structures
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


def _calculate_average_tool_usage(tool_usages: list[dict[str, int]]) -> dict[str, float]:
    """Calculate average tool usage across multiple results.

    Sums up all tool counts and divides by the number of results to get average.
    """
    if not tool_usages:
        return {}

    aggregated = sum((Counter(usage) for usage in tool_usages), Counter())

    # Calculate average (rounded to 2 decimal places)
    num_results = len(tool_usages)
    return {tool: round(count / num_results, 2) for tool, count in aggregated.items()}
