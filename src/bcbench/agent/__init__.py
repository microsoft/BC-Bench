"""Agent module for BC-Bench."""

from bcbench.agent.copilot import get_copilot_version, run_copilot_agent
from bcbench.agent.mini import run_mini_agent

__all__ = ["get_copilot_version", "run_copilot_agent", "run_mini_agent"]
