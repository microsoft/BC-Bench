"""Shared code for CLI-based agents (Claude, Copilot)."""

from bcbench.agent.shared.hooks_parser import parse_tool_usage_from_hooks
from bcbench.agent.shared.hooks_parser import parse_skill_read_diagnostics_from_hooks
from bcbench.agent.shared.lsp import build_al_lsp_plugin
from bcbench.agent.shared.mcp import build_mcp_config
from bcbench.agent.shared.prompt import build_prompt

__all__ = [
	"build_al_lsp_plugin",
	"build_mcp_config",
	"build_prompt",
	"parse_skill_read_diagnostics_from_hooks",
	"parse_tool_usage_from_hooks",
]
