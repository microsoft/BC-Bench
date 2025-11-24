import json
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, model_validator

from bcbench.logger import get_logger
from bcbench.results.base import BaseEvaluationResult
from bcbench.types import EvaluationCategory, ExperimentConfiguration

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

    github_run_id: str | None = None
    experiment: ExperimentConfiguration | None = None

    @model_validator(mode="before")
    @classmethod
    def handle_legacy_format(cls, data: Any) -> Any:
        """Convert legacy flat format to nested experiment structure."""
        if isinstance(data, dict) and "experiment" not in data and any(k in data for k in ["mcp_servers", "custom_instructions", "custom_agent"]):
            mcp_servers_str = data.pop("mcp_servers", None)
            # Convert comma-separated string back to list
            mcp_servers_list = [s.strip() for s in mcp_servers_str.split(",")] if mcp_servers_str else None

            data["experiment"] = {
                "mcp_servers": mcp_servers_list,
                "custom_instructions": data.pop("custom_instructions", False),
                "custom_agent": data.pop("custom_agent", None),
            }
        return data

    @classmethod
    def from_results(cls, results: list[BaseEvaluationResult], run_id: str) -> "EvaluationResultSummary":
        total = len(results)
        resolved = sum(r.resolved for r in results)

        durations = [r.metrics.execution_time for r in results if r.metrics and r.metrics.execution_time is not None]
        prompt_tokens = [r.metrics.prompt_tokens for r in results if r.metrics and r.metrics.prompt_tokens is not None]
        completion_tokens = [r.metrics.completion_tokens for r in results if r.metrics and r.metrics.completion_tokens is not None]

        # Extract experiment configuration from first result (all should be same in a run)
        first_result = results[0]
        experiment = first_result.experiment

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
            github_run_id=run_id,
            experiment=experiment,
        )

    def to_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        # Ensure category is serialized as string value
        data["category"] = self.category.value
        # Round numeric values for readability
        data["average_duration"] = round(data["average_duration"], 1)
        data["average_prompt_tokens"] = round(data["average_prompt_tokens"], 1)
        data["average_completion_tokens"] = round(data["average_completion_tokens"], 1)

        # Flatten experiment fields for backward compatibility with leaderboard format
        if data.get("experiment"):
            exp = data.pop("experiment")
            data["mcp_servers"] = ", ".join(exp["mcp_servers"]) if exp.get("mcp_servers") else None
            data["custom_instructions"] = exp.get("custom_instructions")
            data["custom_agent"] = exp.get("custom_agent")
        else:
            data["mcp_servers"] = None
            data["custom_instructions"] = None
            data["custom_agent"] = None

        return data

    def save(self, output_dir: Path, summary_file: str) -> None:
        output_file = output_dir / summary_file
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), indent=4))

        logger.info(f"Saved evaluation summary to {output_file}")
