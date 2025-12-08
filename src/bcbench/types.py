"""Shared types and data structures used across BC-Bench modules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from bcbench.logger import get_logger

if TYPE_CHECKING:
    from bcbench.dataset import DatasetEntry

__all__ = ["AgentMetrics", "EvaluationContext", "ExperimentConfiguration"]

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

    # Custom agent name used in experiment (if any)
    custom_agent: str | None = None

    def is_empty(self) -> bool:
        """Check if this configuration has all default/empty values.

        An empty configuration means no special experiment settings were used.
        This is useful for comparing with None (no experiment) vs default experiment.
        """
        return self.mcp_servers is None and self.custom_instructions is False and self.custom_agent is None


class EvaluationCategory(str, Enum):
    BUG_FIX = "bug-fix"
    TEST_GENERATION = "test-generation"
    # CODE_REVIEW = "code-review"
    # EVENT_REQUEST = "event-request"


@dataclass
class EvaluationContext:
    """Context object containing all configuration for evaluation pipeline.

    This bundles related configuration together to avoid long parameter lists
    and makes it easier to add new configuration options in the future.
    """

    # Core configuration
    entry: DatasetEntry
    repo_path: Path
    result_dir: Path

    # BC Container configuration
    container_name: str
    password: str
    username: str

    # Agent metadata
    agent_name: str
    model: str

    # Evaluation category
    category: EvaluationCategory

    # Agent execution metrics
    metrics: AgentMetrics | None = None

    # Experiment configuration
    experiment: ExperimentConfiguration | None = None
