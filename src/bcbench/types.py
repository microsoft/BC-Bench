"""Shared types and data structures used across BC-Bench modules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from bcbench.logger import get_logger

if TYPE_CHECKING:
    from bcbench.dataset import BaseDatasetEntry
    from bcbench.evaluate.base import EvaluationPipeline
    from bcbench.results.base import BaseEvaluationResult
    from bcbench.results.summary import EvaluationResultSummary

__all__ = ["AgentMetrics", "AgentType", "ContainerConfig", "EvaluationCategory", "EvaluationContext", "ExperimentConfiguration"]

logger = get_logger(__name__)


class AgentMetrics(BaseModel):
    """Metrics collected during agent execution.

    Separates runtime execution data from experiment configuration.
    """

    model_config = ConfigDict(frozen=True)

    # Total execution time in seconds
    execution_time: float | None = None
    llm_duration: float | None = None

    turn_count: int | None = None

    # Token usage from LLM calls
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    # Tool usage statistics from agent logs
    tool_usage: dict[str, int] | None = None


class ExperimentConfiguration(BaseModel):
    """Configuration for agent experiment execution.

    This encapsulates experiment-related configuration that agents use,
    making it easier to add new configuration options without changing function signatures.
    """

    model_config = ConfigDict(frozen=True)

    # MCP server names used in experiment (if any)
    mcp_servers: list[str] | None = None

    # Custom instructions enabled in experiment
    custom_instructions: bool = False

    # Skills enabled in experiment
    skills_enabled: bool = False

    # Custom agent name used in experiment (if any)
    custom_agent: str | None = None

    def is_empty(self) -> bool:
        """Check if this configuration has all default/empty values.

        An empty configuration means no special experiment settings were used.
        This is useful for comparing with None (no experiment) vs default experiment.
        """
        return self.mcp_servers is None and self.custom_instructions is False and self.skills_enabled is False and self.custom_agent is None


class AgentType(str, Enum):
    COPILOT = "copilot"
    CLAUDE = "claude"

    @property
    def instruction_filename(self) -> str:
        match self:
            case AgentType.COPILOT:
                return "copilot-instructions.md"
            case AgentType.CLAUDE:
                return "CLAUDE.md"
            case _:
                raise ValueError(f"Unknown AgentType: {self}")

    def get_target_dir(self, repo_path: Path) -> Path:
        match self:
            case AgentType.COPILOT:
                return repo_path / ".github"
            case AgentType.CLAUDE:
                return repo_path / ".claude"
            case _:
                raise ValueError(f"Unknown AgentType: {self}")


class EvaluationCategory(str, Enum):
    BUG_FIX = "bug-fix"
    TEST_GENERATION = "test-generation"
    CODE_REVIEW = "code-review"
    # EVENT_REQUEST = "event-request"

    @property
    def dataset_path(self) -> Path:
        from bcbench.config import get_config

        match self:
            case EvaluationCategory.BUG_FIX:
                return get_config().paths.dataset_dir / "bcbench.jsonl"
            case EvaluationCategory.TEST_GENERATION:
                return get_config().paths.dataset_dir / "bcbench.jsonl"
            case EvaluationCategory.CODE_REVIEW:
                return get_config().paths.dataset_dir / "codereview.jsonl"

        raise ValueError(f"Unknown evaluation category: {self}")

    @property
    def entry_class(self) -> type[BaseDatasetEntry]:
        from bcbench.dataset import BugFixEntry, CodeReviewEntry, TestGenEntry

        match self:
            case EvaluationCategory.BUG_FIX:
                return BugFixEntry
            case EvaluationCategory.TEST_GENERATION:
                return TestGenEntry
            case EvaluationCategory.CODE_REVIEW:
                return CodeReviewEntry

        raise ValueError(f"Unknown evaluation category: {self}")

    @property
    def result_class(self) -> type[BaseEvaluationResult]:
        from bcbench.results.bugfix import BugFixResult
        from bcbench.results.codereview import CodeReviewResult
        from bcbench.results.testgeneration import TestGenerationResult

        match self:
            case EvaluationCategory.BUG_FIX:
                return BugFixResult
            case EvaluationCategory.TEST_GENERATION:
                return TestGenerationResult
            case EvaluationCategory.CODE_REVIEW:
                return CodeReviewResult

        raise ValueError(f"Unknown evaluation category: {self}")

    @property
    def summary_class(self) -> type[EvaluationResultSummary]:
        """Returns the EvaluationResultSummary subclass for this category."""
        from bcbench.results.summary import CodeReviewResultSummary, ExecutionBasedEvaluationResultSummary

        match self:
            case EvaluationCategory.BUG_FIX:
                return ExecutionBasedEvaluationResultSummary
            case EvaluationCategory.TEST_GENERATION:
                return ExecutionBasedEvaluationResultSummary
            case EvaluationCategory.CODE_REVIEW:
                return CodeReviewResultSummary

        raise ValueError(f"Unknown evaluation category: {self}")

    @property
    def pipeline(self) -> EvaluationPipeline:
        from bcbench.evaluate import BugFixPipeline, CodeReviewPipeline, TestGenerationPipeline

        match self:
            case EvaluationCategory.BUG_FIX:
                return BugFixPipeline()
            case EvaluationCategory.TEST_GENERATION:
                return TestGenerationPipeline()
            case EvaluationCategory.CODE_REVIEW:
                return CodeReviewPipeline()

        raise ValueError(f"Unknown evaluation category: {self}")


@dataclass(frozen=True)
class ContainerConfig:
    name: str
    username: str
    password: str


@dataclass
class EvaluationContext[E: BaseDatasetEntry]:
    """Context object containing all configuration for evaluation pipeline.

    This bundles related configuration together to avoid long parameter lists
    and makes it easier to add new configuration options in the future.
    """

    # Core configuration
    entry: E
    repo_path: Path
    result_dir: Path

    # Agent metadata
    agent_name: str
    model: str

    # Evaluation category
    category: EvaluationCategory

    # BC Container configuration (optional — not all categories require a container)
    container: ContainerConfig | None = None

    # Agent execution metrics
    metrics: AgentMetrics | None = None

    # Experiment configuration
    experiment: ExperimentConfiguration | None = None

    def get_container(self) -> ContainerConfig:
        if self.container is None:
            raise ValueError(f"Container configuration is required for {self.category.value} evaluation")
        return self.container
