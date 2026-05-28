import json
import shutil
from pathlib import Path
from typing import Any

from jinja2 import Template

from bcbench.agent.shared.altool_paths import build_assembly_probing_paths, compiler_symbol_folder_for_container, set_runtime_version
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)


def _build_server_entry(server: dict[str, Any], template_context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    server_type: str = server["type"]
    server_name: str = server["name"]

    match server_type:
        case "http":
            return server_name, {
                "type": server_type,
                "url": server["url"],
            }
        case "stdio":
            args: list[str] = server["args"]
            rendered_args = [Template(arg).render(**template_context) for arg in args]
            command: str = shutil.which(server["command"]) or server["command"]
            return server_name, {
                "type": server_type,
                "command": command,
                "args": rendered_args,
            }
        case _:
            logger.error(f"Unsupported MCP server type: {server_type}, {server}")
            raise AgentError(f"Unsupported MCP server type: {server_type}")


def build_mcp_config(config: dict[str, Any], entry: BaseDatasetEntry, repo_path: Path, al_mcp: bool = False, container_name: str = "bcbench") -> tuple[str | None, list[str] | None]:
    mcp_servers: list[dict[str, Any]] = config.get("mcp", {}).get("servers", [])

    if not al_mcp:
        mcp_servers = list(filter(lambda s: s.get("name") != "altool", mcp_servers))

    if not mcp_servers:
        return None, None

    template_context: dict[str, str | Path] = {"repo_path": repo_path}

    if al_mcp:
        compiler_folder, symbols_folder = compiler_symbol_folder_for_container(container_name)
        template_context["package_cache_path"] = str(symbols_folder)

        al_server = next(s for s in mcp_servers if s["name"] == "altool")
        project_paths = [str(repo_path / p) for p in entry.project_paths]

        # Insert project paths right after "launchmcpserver" (positional args must precede options)
        insert_idx: int = al_server["args"].index("launchmcpserver") + 1
        al_server["args"][insert_idx:insert_idx] = project_paths

        set_runtime_version(project_paths)

        # Each path must be a separate arg (System.CommandLine expects space-separated values)
        assembly_probing_paths = build_assembly_probing_paths(compiler_folder)
        if assembly_probing_paths:
            al_server["args"].extend(["--assemblyprobingpaths", *assembly_probing_paths])
            logger.info(f"Assembly probing paths: {assembly_probing_paths}")

    mcp_server_names: list[str] = [server["name"] for server in mcp_servers]
    mcp_config = {"mcpServers": dict(map(lambda s: _build_server_entry(s, template_context), mcp_servers))}

    logger.info(f"Using MCP servers: {mcp_server_names}")
    logger.debug(f"MCP configuration: {json.dumps(mcp_config, indent=2)}")

    return json.dumps(mcp_config, separators=(",", ":")), mcp_server_names
