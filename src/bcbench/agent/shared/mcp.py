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


def build_mcp_config(config: dict[str, Any], entry: DatasetEntry, repo_path: Path, al_mcp: bool = False) -> tuple[str | None, list[str] | None]:
    mcp_servers: list[dict[str, Any]] = config.get("mcp", {}).get("servers", [])

    if al_mcp:  # append project paths as separate positional args, no tools will be loaded if project path doesn't contain app.json
        al_server = next(s for s in mcp_servers if s["name"] == "altool")
        al_server["args"].extend(str(repo_path / p) for p in entry.project_paths)
        logger.info("AL MCP server enabled")
    else:
        mcp_servers = list(filter(lambda s: s.get("name") != "altool", mcp_servers))

    if not mcp_servers:
        return None, None

    template_context: dict[str, str | Path] = {"repo_path": repo_path}
    mcp_server_names: list[str] = [server["name"] for server in mcp_servers]
    mcp_config = {"mcpServers": dict(map(lambda s: _build_server_entry(s, template_context), mcp_servers))}

    logger.info(f"Using MCP servers: {mcp_server_names}")
    logger.debug(f"MCP configuration: {json.dumps(mcp_config, indent=2)}")

    return json.dumps(mcp_config, separators=(",", ":")), mcp_server_names
