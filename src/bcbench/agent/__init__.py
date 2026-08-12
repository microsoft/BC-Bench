"""Agent module for BC-Bench."""

from bcbench.agent.bcal import BCalBackendConfig, run_bcal_agent
from bcbench.agent.claude import run_claude_code
from bcbench.agent.copilot import run_copilot_agent

# The AI harnesses are the top-level backends. The code-review category is NOT a fourth
# harness: it runs the Copilot-powered BC-ALAgents review engine, whose backend lives under
# the copilot package (bcbench.agent.copilot.pr_review.run_pr_review_agent) and is reached
# only through the dedicated `code-review` command, not by picking a harness here.
__all__ = ["BCalBackendConfig", "run_bcal_agent", "run_claude_code", "run_copilot_agent"]
