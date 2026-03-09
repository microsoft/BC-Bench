import json
from pathlib import Path
from typing import Any

from jinja2 import Template

from bcbench.dataset import DatasetEntry
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
            return server_name, {
                "type": server_type,
                "command": server["command"],
                "args": rendered_args,
            }
        case _:
            logger.error(f"Unsupported MCP server type: {server_type}, {server}")
            raise AgentError(f"Unsupported MCP server type: {server_type}")


def build_mcp_config(config: dict[str, Any], entry: DatasetEntry, repo_path: Path, al_mcp: bool = False, container_name: str = "bcbench") -> tuple[str | None, list[str] | None]:
    mcp_servers: list[dict[str, Any]] = config.get("mcp", {}).get("servers", [])

    if al_mcp:  # insert project paths right after "launchmcpserver" (positional args must precede options)
        al_server = next(s for s in mcp_servers if s["name"] == "altool")
        insert_idx = al_server["args"].index("launchmcpserver") + 1
        project_paths = [str(repo_path / p) for p in entry.project_paths]
        al_server["args"][insert_idx:insert_idx] = project_paths
        logger.info("AL MCP server enabled")
    else:
        mcp_servers = list(filter(lambda s: s.get("name") != "altool", mcp_servers))

    if not mcp_servers:
        return None, None

    assembly_path = Path(r"C:\ProgramData\BcContainerHelper\compiler") / container_name / "dlls"
    template_context: dict[str, str | Path] = {"repo_path": repo_path, "assembly_probing_path": str(assembly_path)}
    mcp_server_names: list[str] = [server["name"] for server in mcp_servers]
    mcp_config = {"mcpServers": dict(map(lambda s: _build_server_entry(s, template_context), mcp_servers))}

    logger.info(f"Using MCP servers: {mcp_server_names}")
    if assembly_path.exists():
        logger.info(f"Assembly probing path: {assembly_path}")
    else:
        logger.warning(f"Assembly probing path not found: {assembly_path}. Run New-BCCompilerFolderSync to create it.")
    logger.debug(f"MCP configuration: {json.dumps(mcp_config, indent=2)}")

    return json.dumps(mcp_config, separators=(",", ":")), mcp_server_names
