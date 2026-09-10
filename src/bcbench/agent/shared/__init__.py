"""Shared code for CLI-based agents (Claude, Copilot)."""

from bcbench.agent.shared.env import agent_subprocess_env
from bcbench.agent.shared.lsp import build_al_lsp_plugin
from bcbench.agent.shared.mcp import build_mcp_config, build_playbook_mcp_server
from bcbench.agent.shared.mcp_gateway import start_bc_mcp_gateway
from bcbench.agent.shared.playbook_audit import PlaybookUsageTracker
from bcbench.agent.shared.plugin import resolve_config_plugins
from bcbench.agent.shared.prompt import build_prompt
from bcbench.playbooks import PlaybookDefinition, PlaybookManifest, PlaybookSetup, load_playbook_manifest, playbook_revision, resolve_playbook_for_area, resolve_playbook_for_paths

__all__ = [
    "PlaybookDefinition",
    "PlaybookManifest",
    "PlaybookSetup",
    "PlaybookUsageTracker",
    "agent_subprocess_env",
    "build_al_lsp_plugin",
    "build_mcp_config",
    "build_playbook_mcp_server",
    "build_prompt",
    "load_playbook_manifest",
    "playbook_revision",
    "resolve_config_plugins",
    "resolve_playbook_for_area",
    "resolve_playbook_for_paths",
    "start_bc_mcp_gateway",
]
