import json
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel

from bcbench.logger import get_logger
from bcbench.results.base import BaseEvaluationResult
from bcbench.types import EvaluationCategory, ExperimentConfiguration, ToolUsage

logger = get_logger(__name__)


class EvaluationResultSummary(BaseModel):
    total: int
    resolved: int
    failed: int
    build: int

    date: date

    model: str
    agent_name: str
    category: EvaluationCategory

    average_duration: float
    average_prompt_tokens: float
    average_completion_tokens: float
    average_tool_usage: ToolUsage | None = None

    github_run_id: str | None = None
    experiment: ExperimentConfiguration | None = None

    @classmethod
    def from_results(cls, results: Sequence[BaseEvaluationResult], run_id: str) -> "EvaluationResultSummary":
        total = len(results)
        resolved = sum(r.resolved for r in results)

        durations = [r.metrics.execution_time for r in results if r.metrics and r.metrics.execution_time is not None]
        prompt_tokens = [r.metrics.prompt_tokens for r in results if r.metrics and r.metrics.prompt_tokens is not None]
        completion_tokens = [r.metrics.completion_tokens for r in results if r.metrics and r.metrics.completion_tokens is not None]

        # Calculate average tool usage across all results
        tool_usages = [r.metrics.tool_usage for r in results if r.metrics and r.metrics.tool_usage is not None]
        average_tool_usage = _calculate_average_tool_usage(tool_usages) if tool_usages else None

        # Extract experiment configuration from first result (all should be same in a run)
        first_result = results[0]
        experiment = first_result.experiment if first_result.experiment and not first_result.experiment.is_empty() else None

        return cls(
            total=total,
            resolved=resolved,
            failed=total - resolved,
            build=sum(r.build for r in results),
            date=date.today(),
            category=first_result.category,
            model=first_result.model,
            agent_name=first_result.agent_name,
            average_duration=sum(durations) / len(durations) if durations else 0.0,
            average_prompt_tokens=sum(prompt_tokens) / len(prompt_tokens) if prompt_tokens else 0.0,
            average_completion_tokens=sum(completion_tokens) / len(completion_tokens) if completion_tokens else 0.0,
            average_tool_usage=average_tool_usage,
            github_run_id=run_id,
            experiment=experiment,
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


def _calculate_average_tool_usage(tool_usages: list[ToolUsage]) -> ToolUsage:
    """Calculate average tool usage across multiple results.

    Sums up all tool counts and divides by the number of results to get average.
    """
    if not tool_usages:
        return ToolUsage()

    aggregated: dict[str, float] = {}
    for usage in tool_usages:
        for tool_name, count in usage.tool_counts.items():
            aggregated[tool_name] = aggregated.get(tool_name, 0) + count

    # Calculate average (rounded to nearest integer)
    num_results = len(tool_usages)
    average_counts = {tool: round(count / num_results, 2) for tool, count in aggregated.items()}

    return ToolUsage(tool_counts=average_counts)
