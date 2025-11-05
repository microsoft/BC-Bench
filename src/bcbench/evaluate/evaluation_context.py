"""Evaluation context for managing agent evaluation configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

    # Agent-specific options (stored as dict for flexibility)
    agent_options: dict[str, Any] | None = None

    # Agent metrics collected during execution
    agent_metrics: dict[str, float | int] | None = None

    def get_agent_option(self, key: str, default: Any = None) -> Any:
        """Get an agent-specific option.

        Args:
            key: Option key to retrieve
            default: Default value if key is not found

        Returns:
            The option value or default if not found
        """
        if self.agent_options is None:
            return default
        return self.agent_options.get(key, default)
