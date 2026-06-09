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

        Subclasses must override. Keys become display labels (underscores replaced with spaces and title-cased). Values are shown as-is.
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

        durations: list[float] = [r.metrics.execution_time for r in results if r.metrics and r.metrics.execution_time is not None]
        prompt_tokens: list[int] = [r.metrics.prompt_tokens for r in results if r.metrics and r.metrics.prompt_tokens is not None]
        completion_tokens: list[int] = [r.metrics.completion_tokens for r in results if r.metrics and r.metrics.completion_tokens is not None]
        llm_durations: list[float] = [r.metrics.llm_duration for r in results if r.metrics and r.metrics.llm_duration is not None]
        tool_usages: list[dict[str, int]] = [r.metrics.tool_usage for r in results if r.metrics and r.metrics.tool_usage is not None]

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

    def combination_key(self) -> tuple[str, str, str | None, str]:
        """Key for identifying runs of the same agent+model+experiment+benchmark_version combination."""
        experiment_key: str | None = None
        if self.experiment and not self.experiment.is_empty():
            experiment_key = json.dumps(self.experiment.model_dump(mode="json"), sort_keys=True)
        return (self.agent_name, self.model, experiment_key, self.benchmark_version)


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


class JudgeBasedEvaluationResultSummary(EvaluationResultSummary):
    """Summary for judge-scored categories.

    Scoring is performed externally (bceval -> Braintrust/Kusto) and not reflected here;
    this summary only carries the agent-execution aggregates from the base class.
    """

    def display_summary(self) -> dict[str, int | float]:
        return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def calculate_average_tool_usage(tool_usages: list[dict[str, int]]) -> dict[str, float]:
    if not tool_usages:
        return {}

    aggregated = sum((Counter(usage) for usage in tool_usages), Counter())
    num_results = len(tool_usages)
    return {tool: round(count / num_results, 2) for tool, count in aggregated.items()}
