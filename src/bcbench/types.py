"""Shared types and data structures used across BC-Bench modules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from bcbench.dataset import DatasetEntry

__all__ = ["EvaluationContext"]


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

    # Agent metrics collected during execution
    agent_metrics: dict[str, float | int] | None = None

    # MCP server names used in experiment (if any)
    mcp_servers: list[str] | None = None

    # Custom instructions enabled in experiment
    custom_instructions: bool | None = None


class EvaluationCategory(str, Enum):
    BUG_FIX = "bug-fix"
    TEST_GENERATION = "test-generation"
    # CODE_REVIEW = "code-review"
    # EVENT_REQUEST = "event-request"
