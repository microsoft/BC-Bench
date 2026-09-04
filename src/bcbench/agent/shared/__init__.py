"""Shared code for CLI-based agents (Claude, Copilot)."""

from bcbench.agent.shared.altool_source import AlToolSourceCompatibility, prepare_altool_source_compatibility
from bcbench.agent.shared.env import agent_subprocess_env
from bcbench.agent.shared.lsp import build_al_lsp_plugin
from bcbench.agent.shared.mcp import build_mcp_config
from bcbench.agent.shared.mcp_gateway import start_bc_mcp_gateway
from bcbench.agent.shared.plugin import resolve_config_plugins
from bcbench.agent.shared.prompt import build_prompt

__all__ = [
    "AlToolSourceCompatibility",
    "agent_subprocess_env",
    "build_al_lsp_plugin",
    "build_mcp_config",
    "build_prompt",
    "prepare_altool_source_compatibility",
    "resolve_config_plugins",
    "start_bc_mcp_gateway",
]
