"""Agent module for BC-Bench."""

from bcbench.agent.claude import run_claude_code
from bcbench.agent.copilot import run_copilot_agent
from bcbench.agent.mini import run_mini_agent

__all__ = ["run_claude_code", "run_copilot_agent", "run_mini_agent"]
