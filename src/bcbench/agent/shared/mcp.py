import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from jinja2.sandbox import SandboxedEnvironment

from bcbench.agent.shared.altool_paths import build_assembly_probing_paths, compiler_symbol_folder_for_container
from bcbench.agent.shared.managed_clients import ManagedAgentClients
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.types import AgentRuntimeConfig, ContainerConfig

logger = get_logger(__name__)

_jinja = SandboxedEnvironment(autoescape=False)

# Server name for the BC MCP server (toggled via --bc-mcp; needs gateway wiring).
_BC_MCP_SERVER_NAME = "bcmcp"


def _build_server_entry(server: dict[str, Any], template_context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    server_type: str = server["type"]
    server_name: str = server["name"]

    match server_type:
        case "http":
            entry: dict[str, Any] = {
                "type": server_type,
                "url": server["url"],
            }
            headers: dict[str, str] = server.get("headers", {})
            if headers:
                entry["headers"] = headers
            return server_name, entry
        case "stdio":
            args: list[str] = server["args"]
            rendered_args = [_jinja.from_string(arg).render(**template_context) for arg in args]
            command: str = shutil.which(server["command"]) or server["command"]
            stdio_entry: dict[str, Any] = {
                "type": server_type,
                "command": command,
                "args": rendered_args,
            }
            env: dict[str, str] = server.get("env", {})
            if env:
                stdio_entry["env"] = env
            return server_name, stdio_entry
        case _:
            logger.error("Unsupported MCP server type: name=%s type=%s", server_name, server_type)
            raise AgentError(f"Unsupported MCP server type: {server_type}")


def _configure_bc_mcp_server(server: dict[str, Any], gateway_base_url: str | None) -> None:
    """Point the BC MCP server at the local credential-free gateway.

    The gateway (``mcp_gateway.py``) fronts the real BC MCP endpoint: it injects the Basic auth /
    Company / ConfigurationName headers upstream and rejects any non-``/mcp`` path. So the agent's MCP
    config carries only a ``http://127.0.0.1:<port>/.../mcp`` URL with no credentials -- nothing the
    agent can replay against BC's ``/api`` or scrape from the launched process command line.
    """
    if not gateway_base_url:
        raise AgentError("BC MCP requested but the local MCP gateway URL is unavailable.")

    server["url"] = gateway_base_url.rstrip("/") + "/mcp"
    server.pop("headers", None)


def build_mcp_config(
    config: dict[str, Any],
    entry: BaseDatasetEntry,
    repo_path: Path,
    runtime: AgentRuntimeConfig | None = None,
    bc_mcp_gateway_url: str | None = None,
    managed_clients: ManagedAgentClients | None = None,
    require_evaluator_bridge: bool = False,
) -> tuple[str | None, list[str] | None]:
    mcp_servers: list[dict[str, Any]] = deepcopy(config.get("mcp", {}).get("servers", []))

    if runtime is None or not runtime.al_mcp:
        mcp_servers = list(filter(lambda s: s.get("name") != "altool", mcp_servers))

    if runtime is None or not runtime.bc_mcp:
        mcp_servers = list(filter(lambda s: s.get("name") != _BC_MCP_SERVER_NAME, mcp_servers))

    if not mcp_servers:
        return None, None

    template_context: dict[str, str | Path] = {"repo_path": repo_path}

    if runtime is not None and runtime.bc_mcp:
        _configure_bc_mcp_server(next(s for s in mcp_servers if s["name"] == _BC_MCP_SERVER_NAME), bc_mcp_gateway_url)

    if runtime is not None and runtime.al_mcp:
        if require_evaluator_bridge and managed_clients is None:
            raise AgentError("Production AL MCP requires an evaluator-owned bridge")
        container: ContainerConfig = runtime.container
        compiler_folder, symbols_folder = compiler_symbol_folder_for_container(container.name)
        template_context["package_cache_path"] = str(symbols_folder)

        al_server = next(s for s in mcp_servers if s["name"] == "altool")
        project_paths = [str(repo_path / p) for p in entry.project_paths]

        # Insert project paths right after "launchmcpserver" (positional args must precede options)
        insert_idx: int = al_server["args"].index("launchmcpserver") + 1
        al_server["args"][insert_idx:insert_idx] = project_paths

        # Each path must be a separate arg (System.CommandLine expects space-separated values)
        assembly_probing_paths = build_assembly_probing_paths(compiler_folder)
        if assembly_probing_paths:
            al_server["args"].extend(["--assemblyprobingpaths", *assembly_probing_paths])
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
            al_server["env"] = forwarded
            logger.info("Forwarding %d connection environment variables to altool MCP", len(forwarded))

    mcp_server_names: list[str] = [server["name"] for server in mcp_servers]
    mcp_config = {"mcpServers": dict(map(lambda s: _build_server_entry(s, template_context), mcp_servers))}
    if runtime is not None and runtime.al_mcp and managed_clients is not None:
        url = managed_clients.start_al_mcp(mcp_config["mcpServers"]["altool"], repo_path)
        mcp_config["mcpServers"]["altool"] = {"type": "http", "url": url}
    mcp_server_types = {name: entry["type"] for name, entry in mcp_config["mcpServers"].items()}

    logger.info(f"Using MCP servers: {mcp_server_names}")
    logger.debug(
        "MCP configuration summary: servers=%s types=%s al_mcp=%s bc_mcp=%s",
        mcp_server_names,
        mcp_server_types,
        bool(runtime and runtime.al_mcp),
        bool(runtime and runtime.bc_mcp),
    )

    return json.dumps(mcp_config, separators=(",", ":")), mcp_server_names
