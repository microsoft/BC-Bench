"""GitHub Copilot CLI agent module."""

from bcbench_core.agents.copilot import get_copilot_version

from bcbench.agent.copilot.agent import run_copilot_agent

__all__ = ["get_copilot_version", "run_copilot_agent"]
