"""GitHub Copilot CLI agent module."""

from bcbench.agent.copilot.agent import EXPECTED_METRICS as COPILOT_EXPECTED_METRICS
from bcbench.agent.copilot.agent import run_copilot_agent

__all__ = ["COPILOT_EXPECTED_METRICS", "run_copilot_agent"]
