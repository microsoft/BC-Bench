"""Shared code for CLI-based agents (Claude, Copilot)."""

from bcbench.agent.shared.env import agent_subprocess_env
from bcbench.agent.shared.history_gateway import resolve_history_settings, start_history_gateway
from bcbench.agent.shared.history_metrics import attach_history_metrics
from bcbench.agent.shared.lsp import build_al_lsp_plugin
from bcbench.agent.shared.mcp import build_mcp_config
from bcbench.agent.shared.mcp_gateway import start_bc_mcp_gateway
from bcbench.agent.shared.plugin import resolve_config_plugins
from bcbench.agent.shared.prompt import build_prompt

__all__ = [
    "agent_subprocess_env",
    "attach_history_metrics",
    "build_al_lsp_plugin",
    "build_mcp_config",
    "build_prompt",
    "resolve_config_plugins",
    "resolve_history_settings",
    "start_bc_mcp_gateway",
    "start_history_gateway",
]
