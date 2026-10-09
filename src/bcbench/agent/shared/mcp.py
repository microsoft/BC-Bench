import json
import logging
import shutil
from pathlib import Path
from typing import Any

from bcbench_core.container import ContainerConfig
from bcbench_core.exceptions import AgentError
from jinja2.sandbox import SandboxedEnvironment

from bcbench.agent.shared.altool_paths import build_assembly_probing_paths, compiler_symbol_folder_for_container
from bcbench.dataset import BaseDatasetEntry
from bcbench.types import AL_MCP_SERVER_NAME, BC_MCP_SERVER_NAME, AgentConfig, AgentRuntimeConfig, HttpMcpServer, McpServerConfig, StdioMcpServer

logger = logging.getLogger(__name__)

_jinja = SandboxedEnvironment(autoescape=False)


def _build_server_entry(server: McpServerConfig, template_context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    match server:
        case HttpMcpServer():
            entry: dict[str, Any] = {
                "type": server.type,
                "url": server.url,
            }
            if server.headers:
                entry["headers"] = server.headers
            return server.name, entry
        case StdioMcpServer():
            rendered_args = [_jinja.from_string(arg).render(**template_context) for arg in server.args]
            command: str = shutil.which(server.command) or server.command
            stdio_entry: dict[str, Any] = {
                "type": server.type,
                "command": command,
                "args": rendered_args,
            }
            if server.env:
                stdio_entry["env"] = server.env
            return server.name, stdio_entry


def _configure_bc_mcp_server(server: HttpMcpServer, gateway_base_url: str | None) -> None:
    """Point the BC MCP server at the local credential-free gateway.

    The gateway (``mcp_gateway.py``) fronts the real BC MCP endpoint: it injects the Basic auth /
    Company / ConfigurationName headers upstream and rejects any non-``/mcp`` path. So the agent's MCP
    config carries only a ``http://127.0.0.1:<port>/.../mcp`` URL with no credentials -- nothing the
    agent can replay against BC's ``/api`` or scrape from the launched process command line.
    """
    if not gateway_base_url:
        raise AgentError("BC MCP requested but the local MCP gateway URL is unavailable.")

    server.url = gateway_base_url.rstrip("/") + "/mcp"
    server.headers = {}


def build_mcp_config(
    config: AgentConfig,
    entry: BaseDatasetEntry,
    repo_path: Path,
    runtime: AgentRuntimeConfig | None = None,
    bc_mcp_gateway_url: str | None = None,
) -> tuple[str | None, list[str] | None]:
    mcp_servers: list[McpServerConfig] = list(config.mcp.servers)

    if runtime is None or not runtime.al_mcp:
        mcp_servers = list(filter(lambda s: s.name != AL_MCP_SERVER_NAME, mcp_servers))

    if runtime is None or not runtime.bc_mcp:
        mcp_servers = list(filter(lambda s: s.name != BC_MCP_SERVER_NAME, mcp_servers))

    if not mcp_servers:
        return None, None

    template_context: dict[str, str | Path] = {"repo_path": repo_path}

    if runtime is not None and runtime.bc_mcp:
        _configure_bc_mcp_server(next(s for s in mcp_servers if isinstance(s, HttpMcpServer) and s.name == BC_MCP_SERVER_NAME), bc_mcp_gateway_url)

    if runtime is not None and runtime.al_mcp:
        container: ContainerConfig = runtime.container
        compiler_folder, symbols_folder = compiler_symbol_folder_for_container(container.name)
        template_context["package_cache_path"] = str(symbols_folder)

        al_server = next(s for s in mcp_servers if isinstance(s, StdioMcpServer) and s.name == AL_MCP_SERVER_NAME)
        project_paths = [str(repo_path / p) for p in entry.project_paths]

        # Insert project paths right after "launchmcpserver" (positional args must precede options)
        insert_idx: int = al_server.args.index("launchmcpserver") + 1
        al_server.args[insert_idx:insert_idx] = project_paths

        # Each path must be a separate arg (System.CommandLine expects space-separated values)
        assembly_probing_paths = build_assembly_probing_paths(compiler_folder)
        if assembly_probing_paths:
            al_server.args.extend(["--assemblyprobingpaths", *assembly_probing_paths])
            logger.info(f"Assembly probing paths: {assembly_probing_paths}")

        # altool defines these environment variable names as its connection-config interface. Values
        # are sourced from typed CLI configuration rather than reading the harness environment here.
        forwarded = {
            key: value
            for key, value in {
                "BC_SERVER_URL": container.server_url,
                "BC_SERVER_INSTANCE": container.server_instance,
                "BC_SERVER_USERNAME": container.username,
                "BC_SERVER_PASSWORD": container.password,
            }.items()
            if value
        }
        if forwarded:
            al_server.env = forwarded
            logger.info(f"Forwarding env vars to altool MCP: {list(forwarded.keys())}")

    mcp_server_names: list[str] = [server.name for server in mcp_servers]
    mcp_config = {"mcpServers": dict(map(lambda s: _build_server_entry(s, template_context), mcp_servers))}

    logger.info(f"Using MCP servers: {mcp_server_names}")
    # The BC container password (if forwarded to altool) is already masked in CI logs via ::add-mask::,
    # and the bcmcp entry is credential-free (the gateway injects auth upstream), so no extra redaction.
    logger.debug(f"MCP configuration: {json.dumps(mcp_config, indent=2)}")

    return json.dumps(mcp_config, separators=(",", ":")), mcp_server_names
