"""Base evaluation result class with shared metrics across all evaluation categories."""

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from bcbench.logger import get_logger
from bcbench.types import EvaluationCategory, EvaluationContext

logger = get_logger(__name__)

# Type variable for proper return type hints in class methods
T = TypeVar("T", bound="BaseEvaluationResult")


class BaseEvaluationResult(BaseModel):
    """Base class for all evaluation results with shared metrics across categories."""

    instance_id: str
    project: str  # TODO: move to category-specific subclasses?
    model: str
    agent_name: str
    category: EvaluationCategory

    resolved: bool
    build: bool
    timeout: bool = False

    generated_patch: str = ""
    error_message: str | None = None

    agent_execution_time: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    mcp_servers: list[str] | None = None
    custom_instructions: bool | None = None
    custom_agent: str | None = None

    @classmethod
    def _create_from_context(
        cls: type[T],
        context: "EvaluationContext",
        resolved: bool,
        build: bool,
        error_message: str | None = None,
        generated_patch: str = "",
        **kwargs: Any,
    ) -> T:
        """Create result from EvaluationContext with validation and metric extraction.

        Args:
            context: Evaluation context with configuration
            resolved: Whether the evaluation was successful
            build: Whether the build succeeded
            error_message: Optional error message if evaluation failed
            generated_patch: The generated patch content
            **kwargs: Additional category-specific fields

        Returns:
            Result instance (base or category-specific subclass)
        """
        prompt_tokens = None
        completion_tokens = None
        agent_execution_time = None
        mcp_servers = None
        custom_instructions = None
        custom_agent = None

        # Extract metrics from AgentMetrics object
        if context.metrics:
            agent_execution_time = context.metrics.execution_time
            prompt_tokens = context.metrics.prompt_tokens
            completion_tokens = context.metrics.completion_tokens

        # Extract experiment configuration
        if context.experiment:
            mcp_servers = context.experiment.mcp_servers
            custom_instructions = context.experiment.custom_instructions
            custom_agent = context.experiment.custom_agent

        # Warn about missing critical metrics that affect result quality
        if not context.metrics:
            logger.warning(f"Creating result for {context.entry.instance_id} with no agent metrics - performance data will be unavailable")
        else:
            missing_metrics = []
            if agent_execution_time is None:
                missing_metrics.append("execution_time")
            if prompt_tokens is None:
                missing_metrics.append("prompt_tokens")
            if completion_tokens is None:
                missing_metrics.append("completion_tokens")

            if missing_metrics:
                logger.warning(f"Result for {context.entry.instance_id} missing metrics: {', '.join(missing_metrics)}")

        project = context.entry.extract_project_name()
        return cls(
            instance_id=context.entry.instance_id,
            project=project,
            resolved=resolved,
            build=build,
            model=context.model,
            category=context.category,
            agent_name=context.agent_name,
            generated_patch=generated_patch,
            error_message=error_message,
            agent_execution_time=agent_execution_time,
            prompt_tokens=int(prompt_tokens) if prompt_tokens is not None else None,
            completion_tokens=int(completion_tokens) if completion_tokens is not None else None,
            mcp_servers=mcp_servers,
            custom_instructions=custom_instructions,
            custom_agent=custom_agent,
            **kwargs,
        )

    @classmethod
    def create_success(cls: type[T], context: "EvaluationContext", generated_patch: str, **kwargs: Any) -> T:
        return cls._create_from_context(context, resolved=True, build=True, generated_patch=generated_patch, **kwargs)

    @classmethod
    def create_build_failure(cls: type[T], context: "EvaluationContext", generated_patch: str, error_msg: str, **kwargs: Any) -> T:
        return cls._create_from_context(context, resolved=False, build=False, error_message=error_msg, generated_patch=generated_patch, **kwargs)

    @classmethod
    def create_test_failure(cls: type[T], context: "EvaluationContext", generated_patch: str, error_msg: str = "Tests failed", **kwargs: Any) -> T:
        return cls._create_from_context(context, resolved=False, build=True, error_message=error_msg, generated_patch=generated_patch, **kwargs)

    @classmethod
    def create_agent_timeout_failure(cls: type[T], context: "EvaluationContext", **kwargs: Any) -> T:
        return cls._create_from_context(context, resolved=False, build=False, timeout=True, error_message="Agent timed out", **kwargs)

    def save(self, output_dir: Path, result_file: str) -> None:
        output_file = output_dir / result_file
        with open(output_file, "a", encoding="utf-8") as f:
            result_dict = self.model_dump(mode="json")
            result_dict["category"] = self.category.value
            f.write(json.dumps(result_dict) + "\n")

        logger.info(f"Saved evaluation result for {self.instance_id} to {output_file}")


def create_result_from_json(payload: dict[str, Any]) -> BaseEvaluationResult:
    """Create appropriate result instance from JSON payload based on category.

    Args:
        payload: Dictionary containing result data

    Returns:
        BugFixResult or TestGenerationResult instance based on category
    """
    # Import here to avoid circular dependencies
    from bcbench.results.bugfix import BugFixResult
    from bcbench.results.testgeneration import TestGenerationResult

    category = EvaluationCategory(payload["category"])

    match category:
        case EvaluationCategory.BUG_FIX:
            return BugFixResult.model_validate(payload)
        case EvaluationCategory.TEST_GENERATION:
            return TestGenerationResult.model_validate(payload)
        case _:
            raise ValueError(f"Unknown evaluation category: {category}")
