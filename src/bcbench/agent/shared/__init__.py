"""Shared code for CLI-based agents (Claude, Copilot)."""

from bcbench.agent.shared.hooks_parser import parse_tool_usage_from_hooks
from bcbench.agent.shared.lsp import build_claude_lsp_plugin, build_copilot_lsp_config
from bcbench.agent.shared.mcp import build_mcp_config
from bcbench.agent.shared.prompt import build_prompt

__all__ = ["build_claude_lsp_plugin", "build_copilot_lsp_config", "build_mcp_config", "build_prompt", "parse_tool_usage_from_hooks"]
