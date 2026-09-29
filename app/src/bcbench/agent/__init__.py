"""Agent module for BC-Bench."""

from bcbench.agent.bcal import BCalBackendConfig, run_bcal_agent
from bcbench.agent.claude import get_claude_version, run_claude_code
from bcbench.agent.copilot import get_copilot_version, run_copilot_agent
from bcbench.agent.pr_review import get_pr_review_version, run_pr_review_agent

__all__ = ["BCalBackendConfig", "get_claude_version", "get_copilot_version", "get_pr_review_version", "run_bcal_agent", "run_claude_code", "run_copilot_agent", "run_pr_review_agent"]
