import json
import tomllib
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from bcbench.logger import get_logger
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.metrics import bootstrap_ci, pass_hat_k
from bcbench.types import EvaluationCategory, ExperimentConfiguration

logger = get_logger(__name__)


def _get_benchmark_version() -> str:
    pyproject_path = Path(__file__).parent.parent.parent.parent / "pyproject.toml"
    if not pyproject_path.exists():
        try:
            from importlib.metadata import version

            return version("bcbench")
        except Exception:
            return "unknown"
    with open(pyproject_path, "rb") as f:
        return tomllib.load(f).get("project", {}).get("version", "unknown")


class EvaluationResultSummary(BaseModel, ABC):
    """Base summary for a single evaluation run across all instances.

    Contains agent metrics common to every category (tokens, duration, tool usage).
    Category-specific metrics (resolved, build, etc.) live on subclasses.
    """

    total: int

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

    benchmark_version: str

    @abstractmethod
    def display_summary(self) -> dict[str, int | float]:
        """Return category-specific metrics for console/GitHub summary display.

        Subclasses must override. Keys become display labels (underscores replaced
        with spaces and title-cased). Values are shown as-is.
        """

    @classmethod
    def from_results(cls, results: Sequence[BaseEvaluationResult], run_id: str) -> "EvaluationResultSummary":
        """Create a summary from a list of per-instance results.

        When called on the base class, dispatches to the correct subclass.
        Subclasses override, call super().from_results(), and extend via model_copy().
        """
        if cls is EvaluationResultSummary:
            summary_cls = results[0].category.summary_class
            return summary_cls.from_results(results, run_id)

        durations = [r.metrics.execution_time for r in results if r.metrics and r.metrics.execution_time is not None]
        prompt_tokens = [r.metrics.prompt_tokens for r in results if r.metrics and r.metrics.prompt_tokens is not None]
        completion_tokens = [r.metrics.completion_tokens for r in results if r.metrics and r.metrics.completion_tokens is not None]
        llm_durations = [r.metrics.llm_duration for r in results if r.metrics and r.metrics.llm_duration is not None]
        tool_usages = [r.metrics.tool_usage for r in results if r.metrics and r.metrics.tool_usage is not None]

        first_result = results[0]
        experiment = first_result.experiment if first_result.experiment and not first_result.experiment.is_empty() else None

        return cls(
            total=len(results),
            date=date.today(),
            category=first_result.category,
            model=first_result.model,
            agent_name=first_result.agent_name,
            average_duration=sum(durations) / len(durations) if durations else 0.0,
            average_prompt_tokens=sum(prompt_tokens) / len(prompt_tokens) if prompt_tokens else 0.0,
            average_completion_tokens=sum(completion_tokens) / len(completion_tokens) if completion_tokens else 0.0,
            average_llm_duration=sum(llm_durations) / len(llm_durations) if llm_durations else 0.0,
            average_tool_usage=calculate_average_tool_usage(tool_usages) if tool_usages else None,
            github_run_id=run_id,
            experiment=experiment,
            benchmark_version=_get_benchmark_version(),
        )

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "EvaluationResultSummary":
        category = EvaluationCategory(payload["category"])
        return category.summary_class.model_validate(payload)

    def to_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["average_duration"] = round(data["average_duration"], 1)
        data["average_prompt_tokens"] = round(data["average_prompt_tokens"], 1)
        data["average_completion_tokens"] = round(data["average_completion_tokens"], 1)
        data["average_llm_duration"] = round(data["average_llm_duration"], 1) if data["average_llm_duration"] is not None else None
        return data

    def save(self, output_dir: Path, summary_file: str) -> None:
        output_file = output_dir / summary_file
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), indent=4))

        logger.info(f"Saved evaluation summary to {output_file}")


class ExecutionBasedEvaluationResultSummary(EvaluationResultSummary):
    """Summary for categories with binary pass/fail outcomes (bug-fix, test-generation).

    Fields match the original flat layout in the leaderboard JSON files.
    """

    resolved: int = 0
    failed: int = 0
    build: int = 0
    percentage: float = 0.0

    # Per-instance pass/fail for aggregate metrics (pass^k, CI)
    instance_results: dict[str, bool] = Field(default_factory=dict)

    def display_summary(self) -> dict[str, int | float]:
        return {
            "resolved": self.resolved,
            "failed": self.failed,
            "build": self.build,
        }

    @classmethod
    def from_results(cls, results: Sequence[BaseEvaluationResult], run_id: str) -> "ExecutionBasedEvaluationResultSummary":
        from bcbench.results.base import ExecutionBasedEvaluationResult

        summary = super().from_results(results, run_id)
        assert isinstance(summary, ExecutionBasedEvaluationResultSummary)
        total = summary.total

        resolved = sum(1 for r in results if isinstance(r, ExecutionBasedEvaluationResult) and r.resolved)
        build = sum(1 for r in results if isinstance(r, ExecutionBasedEvaluationResult) and r.build)
        instance_results = {r.instance_id: (isinstance(r, ExecutionBasedEvaluationResult) and r.resolved) for r in results}

        return summary.model_copy(
            update={
                "resolved": resolved,
                "failed": total - resolved,
                "build": build,
                "percentage": round(resolved / total * 100, 1) if total else 0.0,
                "instance_results": instance_results,
            }
        )


# ---------------------------------------------------------------------------
# Leaderboard aggregation (execution-based categories only)
# ---------------------------------------------------------------------------


class LeaderboardAggregate(BaseModel):
    """Aggregate metrics across multiple runs. Execution-based categories only for now."""

    model: str
    agent_name: str
    category: EvaluationCategory
    experiment: ExperimentConfiguration | None = None

    total: int
    num_runs: int

    average: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    pass_hat_5: float | None = None

    average_duration: float | None = None

    benchmark_version: str

    @classmethod
    def from_runs(cls, runs: Sequence[ExecutionBasedEvaluationResultSummary]) -> "LeaderboardAggregate":
        if not runs:
            raise ValueError("Cannot create aggregate from empty runs list")

        first_run = runs[0]
        total = first_run.total
        num_runs = len(runs)
        benchmark_version = first_run.benchmark_version

        unique_totals = {r.total for r in runs}
        if len(unique_totals) > 1:
            logger.warning(f"Aggregating runs with different instance counts for '{first_run.agent_name}' + '{first_run.model}': {sorted(unique_totals)}. pass^k metrics may be misleading.")

        # Average duration across runs
        durations = [r.average_duration for r in runs if r.average_duration]
        average_duration = sum(durations) / len(durations) if durations else None

        # Collect per-instance results across runs for pass^5
        instance_resolved: dict[str, list[bool]] = {}
        for run in runs:
            for instance_id, outcome in run.instance_results.items():
                if instance_id not in instance_resolved:
                    instance_resolved[instance_id] = []
                instance_resolved[instance_id].append(bool(outcome))

        # Per-run scores for average and CI
        per_run_rates = [run.resolved / run.total for run in runs if run.total > 0]
        avg = round(sum(per_run_rates) / len(per_run_rates), 3) if per_run_rates else None
        ci_result = bootstrap_ci(per_run_rates)
        ci_low = round(ci_result["ci_low"], 3) if ci_result["ci_low"] is not None else None
        ci_high = round(ci_result["ci_high"], 3) if ci_result["ci_high"] is not None else None

        pass_hat_5_val = _calculate_pass_hat_k(instance_resolved, 5, num_runs) if num_runs >= 5 else None

        return cls(
            model=first_run.model,
            agent_name=first_run.agent_name,
            category=first_run.category,
            experiment=first_run.experiment,
            total=total,
            num_runs=num_runs,
            average=avg,
            ci_low=ci_low,
            ci_high=ci_high,
            pass_hat_5=pass_hat_5_val,
            average_duration=round(average_duration, 1) if average_duration else None,
            benchmark_version=benchmark_version,
        )


class Leaderboard(BaseModel):
    """Leaderboard for execution-based categories only.

    Non-execution-based categories (e.g. code-review) will need a different
    leaderboard model once they are introduced.
    """

    runs: list[ExecutionBasedEvaluationResultSummary]
    aggregate: list[LeaderboardAggregate]

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _calculate_pass_hat_k(instance_resolved: dict[str, list[bool]], k: int, num_trials: int) -> float:
    if num_trials < k:
        return 0.0

    total_pass_hat_k: float = 0.0
    for results in instance_resolved.values():
        success_count = sum(results[:num_trials])
        total_pass_hat_k += pass_hat_k(num_trials, success_count, k)

    return round(total_pass_hat_k / len(instance_resolved), 3)


def calculate_average_tool_usage(tool_usages: list[dict[str, int]]) -> dict[str, float]:
    if not tool_usages:
        return {}

    aggregated = sum((Counter(usage) for usage in tool_usages), Counter())
    num_results = len(tool_usages)
    return {tool: round(count / num_results, 2) for tool, count in aggregated.items()}
