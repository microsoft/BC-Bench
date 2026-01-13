"""Shared code for CLI-based agents (Claude, Copilot)."""

from bcbench.agent.shared.mcp import build_mcp_config
from bcbench.agent.shared.prompt import build_prompt

__all__ = ["build_mcp_config", "build_prompt"]
