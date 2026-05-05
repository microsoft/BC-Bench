"""Agent module for BC-Bench."""

from bcbench.agent.bcal import run_bcal_agent
from bcbench.agent.claude import run_claude_code
from bcbench.agent.copilot import run_copilot_agent

__all__ = ["run_bcal_agent", "run_claude_code", "run_copilot_agent"]
