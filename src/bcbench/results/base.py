"""Base evaluation result class with shared metrics across all evaluation categories."""

import json
import re
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel

from bcbench.logger import get_logger
from bcbench.types import AgentMetrics, EvaluationCategory, EvaluationContext, ExperimentConfiguration

logger = get_logger(__name__)


def natural_sort_key(value: str) -> tuple[object, ...]:
    """Split a string into a tuple suitable for human-friendly sorting.

    "test__name-2" sorts before "test__name-10" because numeric runs are compared as integers.
    Non-numeric segments are lowercased for case-insensitive ordering.
    """
    return tuple(int(segment) if segment.isdigit() else segment.lower() for segment in re.split(r"(\d+)", value))


class BaseEvaluationResult(BaseModel):
    """Base class for all evaluation results with shared metrics across categories."""

    instance_id: str
    project: str
    model: str
    agent_name: str
    category: EvaluationCategory

    timeout: bool = False

    output: str = ""
    error_message: str | None = None

    metrics: AgentMetrics | None = None
    experiment: ExperimentConfiguration | None = None

    @classmethod
    def _base_fields(cls, context: "EvaluationContext") -> dict[str, Any]:
        if not context.metrics:
            logger.warning(f"Creating result for {context.entry.instance_id} with no agent metrics - performance data will be unavailable")
        elif missing_metrics := [name for name in AgentMetrics.model_fields if getattr(context.metrics, name) is None]:
            logger.warning(f"Result for {context.entry.instance_id} missing metrics: {', '.join(missing_metrics)}")

        return {
            "instance_id": context.entry.instance_id,
            "project": context.entry.extract_project_name(),
            "model": context.model.replace(".", "-"),
            "category": context.category,
            "agent_name": context.agent_name,
            "metrics": context.metrics,
            "experiment": context.experiment,
        }

    @classmethod
    def create_agent_timeout_failure(cls, context: "EvaluationContext") -> Self:
        return cls(**cls._base_fields(context), timeout=True, error_message="Agent timed out")

    def save(self, output_dir: Path, result_file: str) -> None:
        output_file = output_dir / result_file
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(output_file, "a", encoding="utf-8") as f:
            result_dict = self.model_dump(mode="json")
            # Per-instance JSONL result files are uploaded as workflow artifacts and are the only inputs required by the summarize-results workflow.
            f.write(json.dumps(result_dict) + "\n")

        logger.info(f"Saved evaluation result for {self.instance_id} to {output_file}")

    @property
    def status_label(self) -> str:
        """Short human-readable label for the result status shown in tables (e.g. 'Completed', 'Timeout')."""
        if self.timeout:
            return "Timeout"
        if self.error_message:
            return "Error"
        return "Completed"

    @property
    def category_metrics(self) -> dict[str, int | float | bool]:
        """Category-specific metrics included in bceval export metadata.

        Keys become metadata fields; values must be JSON-serializable scalars.
        Subclasses override to add metrics like 'resolved', 'build', etc.
        """
        return {}

    @property
    def display_row(self) -> dict[str, str]:
        """Extra columns for per-instance detail tables.

        Keys are column headers; values are the cell text for this result.
        Subclasses override to surface category-specific per-instance info.
        """
        return {}

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "BaseEvaluationResult":
        category = EvaluationCategory(payload["category"])
        return category.result_class.model_validate(payload)


class ExecutionBasedEvaluationResult(BaseEvaluationResult):
    """Result for categories that involve building/compiling AL code and have binary pass/fail outcomes."""

    resolved: bool = False
    build: bool = False

    @classmethod
    def create_success(cls, context: "EvaluationContext", output: str) -> Self:
        return cls(**cls._base_fields(context), output=output, resolved=True, build=True)

    @classmethod
    def create_build_failure(cls, context: "EvaluationContext", output: str, error_message: str) -> Self:
        return cls(**cls._base_fields(context), output=output, error_message=error_message, resolved=False, build=False)

    @property
    def status_label(self) -> str:
        if self.timeout:
            return "Timeout"
        return "Success" if self.resolved else "Failed"

    @property
    def category_metrics(self) -> dict[str, int | float | bool]:
        return {"resolved": self.resolved, "build": self.build}


class JudgeBasedEvaluationResult(BaseEvaluationResult):
    """Result for categories scored by LLM-as-judge (e.g. lm_checklist).

    The local pipeline only persists the agent's raw output; actual scoring is performed downstream by bceval
    and lives in the external scoring backend (e.g. Kusto) not in these local artifacts.
    """

    @classmethod
    def create_raw(cls, context: "EvaluationContext", output: str) -> Self:
        return cls(**cls._base_fields(context), output=output)

    @classmethod
    def create_failure(cls, context: "EvaluationContext", output: str, error_message: str) -> Self:
        return cls(**cls._base_fields(context), output=output, error_message=error_message)

    @property
    def status_label(self) -> str:
        if self.timeout:
            return "Timeout"
        if self.error_message:
            return "Error"
        return "Unscored"
