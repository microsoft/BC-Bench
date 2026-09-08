"""GitHub Copilot CLI agent module."""

from bcbench.agent.copilot.agent import run_copilot_agent
from bcbench.agent.copilot.cli import get_copilot_version

__all__ = ["get_copilot_version", "run_copilot_agent"]
