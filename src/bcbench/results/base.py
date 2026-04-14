"""Base evaluation result class with shared metrics across all evaluation categories."""

import json
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel

from bcbench.logger import get_logger
from bcbench.types import AgentMetrics, EvaluationCategory, EvaluationContext, ExperimentConfiguration

logger = get_logger(__name__)


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
    def _create_from_context(
        cls,
        context: "EvaluationContext",
        error_message: str | None = None,
        output: str = "",
        **kwargs: Any,
    ) -> Self:
        if not context.metrics:
            logger.warning(f"Creating result for {context.entry.instance_id} with no agent metrics - performance data will be unavailable")
        elif missing_metrics := [name for name in AgentMetrics.model_fields if getattr(context.metrics, name) is None]:
            logger.warning(f"Result for {context.entry.instance_id} missing metrics: {', '.join(missing_metrics)}")

        project = context.entry.extract_project_name()
        return cls(
            instance_id=context.entry.instance_id,
            project=project,
            model=context.model.replace(".", "-"),
            category=context.category,
            agent_name=context.agent_name,
            output=output,
            error_message=error_message,
            metrics=context.metrics,
            experiment=context.experiment,
            **kwargs,
        )

    @classmethod
    def create_agent_timeout_failure(cls, context: "EvaluationContext", **kwargs: Any) -> Self:
        return cls._create_from_context(context, timeout=True, error_message="Agent timed out", **kwargs)

    def save(self, output_dir: Path, result_file: str) -> None:
        output_file = output_dir / result_file
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
    def create_success(cls, context: "EvaluationContext", output: str, **kwargs: Any) -> Self:
        return cls._create_from_context(context, output=output, resolved=True, build=True, **kwargs)

    @classmethod
    def create_build_failure(cls, context: "EvaluationContext", output: str, error_msg: str, **kwargs: Any) -> Self:
        return cls._create_from_context(context, output=output, error_message=error_msg, resolved=False, build=False, **kwargs)

    @classmethod
    def create_test_failure(cls, context: "EvaluationContext", output: str, error_msg: str = "Tests failed", **kwargs: Any) -> Self:
        return cls._create_from_context(context, output=output, error_message=error_msg, resolved=False, build=True, **kwargs)

    @property
    def status_label(self) -> str:
        if self.timeout:
            return "Timeout"
        return "Success" if self.resolved else "Failed"

    @property
    def category_metrics(self) -> dict[str, int | float | bool]:
        return {"resolved": self.resolved, "build": self.build}
