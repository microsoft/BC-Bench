"""Agent module for BC-Bench."""

from bcbench.agent.bcal import BCalBackendConfig, run_bcal_agent
from bcbench.agent.claude import run_claude_code
from bcbench.agent.copilot import run_copilot_agent
from bcbench.agent.engine import run_engine_review

# Each run_* is a distinct execution backend/harness, not a flavor of another.
# run_engine_review is separate from run_copilot_agent on purpose: BC-Bench spawns the
# PROD BC-ALAgents PowerShell orchestrator (which internally spawns its own Copilot), so
# BC-Bench does not own the prompt/MCP/LSP here and the two share almost no parameters.
# code-review is routed to the engine at the command layer (see commands/run.py), so from
# the user's side it still lives under the copilot command; only the implementation is split.
__all__ = ["BCalBackendConfig", "run_bcal_agent", "run_claude_code", "run_copilot_agent", "run_engine_review"]
