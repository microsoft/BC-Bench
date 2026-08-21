import base64
import json
import os
import shutil
from pathlib import Path
from typing import Any

from jinja2.sandbox import SandboxedEnvironment

from bcbench.agent.shared.altool_paths import build_assembly_probing_paths, compiler_symbol_folder_for_container
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)

_jinja = SandboxedEnvironment(autoescape=False)

# Server names for the independently-toggled MCP servers.
_BC_MCP_SERVER_NAME = "bcmcp"
_MS_LEARN_MCP_SERVER_NAME = "mslearn"
# Must match the configuration name the setup-time AL app creates (scripts/al/mcp-config-setup).
_BC_MCP_CONFIGURATION_NAME = "BCBench"


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
            logger.error(f"Unsupported MCP server type: {server_type}, {server}")
            raise AgentError(f"Unsupported MCP server type: {server_type}")


def _configure_bc_mcp_server(server: dict[str, Any]) -> None:
    """Fill the BC MCP server's endpoint + auth/company headers from the container connection env vars.

    ``BC_MCP_URL``/``BC_MCP_COMPANY`` are exported by ``Setup-ContainerAndRepository.ps1``. Auth is
    Basic over the reused ``BC_SERVER_*`` credentials (validated against NAV's MCP client). Omitting the
    Company header would switch the server into cross-company dynamic mode, so it is only sent when a
    company is known. Which tools the server exposes is decided server-side by the MCP configuration
    the setup-time AL app provisions, not here.
    """
    base_url = os.environ.get("BC_MCP_URL")
    if not base_url:
        raise AgentError("BC MCP requested but BC_MCP_URL is not set; container setup must export it.")

    username = os.environ.get("BC_SERVER_USERNAME", "")
    password = os.environ.get("BC_SERVER_PASSWORD", "")
    basic_auth = base64.b64encode(f"{username}:{password}".encode()).decode()

    headers: dict[str, str] = {
        "Authorization": f"Basic {basic_auth}",
        "ConfigurationName": _BC_MCP_CONFIGURATION_NAME,
    }
    company = os.environ.get("BC_MCP_COMPANY")
    if company:
        headers["Company"] = company

    server["url"] = base_url.rstrip("/") + "/mcp"
    server["headers"] = headers


def build_mcp_config(
    config: dict[str, Any],
    entry: BaseDatasetEntry,
    repo_path: Path,
    al_mcp: bool = False,
    bc_mcp: bool = False,
    ms_learn_mcp: bool = False,
    container_name: str = "bcbench",
) -> tuple[str | None, list[str] | None]:
    mcp_servers: list[dict[str, Any]] = config.get("mcp", {}).get("servers", [])

    if not al_mcp:
        mcp_servers = list(filter(lambda s: s.get("name") != "altool", mcp_servers))

    if not bc_mcp:
        mcp_servers = list(filter(lambda s: s.get("name") != _BC_MCP_SERVER_NAME, mcp_servers))

    if not ms_learn_mcp:
        mcp_servers = list(filter(lambda s: s.get("name") != _MS_LEARN_MCP_SERVER_NAME, mcp_servers))

    if not mcp_servers:
        return None, None

    template_context: dict[str, str | Path] = {"repo_path": repo_path}

    if bc_mcp:
        _configure_bc_mcp_server(next(s for s in mcp_servers if s["name"] == _BC_MCP_SERVER_NAME))

    if al_mcp:
        compiler_folder, symbols_folder = compiler_symbol_folder_for_container(container_name)
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

        # forward BC_SERVER_* environment variables explicitly
        forwarded = {k: os.environ[k] for k in ("BC_SERVER_URL", "BC_SERVER_INSTANCE", "BC_SERVER_USERNAME", "BC_SERVER_PASSWORD") if os.environ.get(k)}
        if forwarded:
            al_server["env"] = forwarded
            logger.info(f"Forwarding env vars to altool MCP: {list(forwarded.keys())}")

    mcp_server_names: list[str] = [server["name"] for server in mcp_servers]
    mcp_config = {"mcpServers": dict(map(lambda s: _build_server_entry(s, template_context), mcp_servers))}

    logger.info(f"Using MCP servers: {mcp_server_names}")
    logger.debug(f"MCP configuration: {json.dumps(mcp_config, indent=2)}")

    return json.dumps(mcp_config, separators=(",", ":")), mcp_server_names
