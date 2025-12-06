import json
from pathlib import Path
from typing import Any

from jinja2 import Template

from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)


def _build_server_entry(server: dict[str, Any], template_context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    server_type: str = server["type"]
    server_name: str = server["name"]
    tools: list[str] = server["tools"]

    match server_type:
        case "http":
            return server_name, {
                "type": server_type,
                "url": server["url"],
                "tools": tools,
            }
        case "local":
            args: list[str] = server["args"]
            rendered_args = [Template(arg).render(**template_context) for arg in args]
            return server_name, {
                "type": server_type,
                "command": server["command"],
                "args": rendered_args,
                "tools": tools,
            }
        case _:
            logger.error(f"Unsupported MCP server type: {server_type}, {server}")
            raise AgentError(f"Unsupported MCP server type: {server_type}")


def build_mcp_config(copilot_config: dict[str, Any], repo_path: Path) -> tuple[str | None, list[str] | None]:
    # following docs: https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/use-copilot-agents/coding-agent/extend-coding-agent-with-mcp
    mcp_servers: list[dict[str, Any]] = copilot_config.get("mcp", {}).get("servers", [])
    if not mcp_servers:
        return None, None

    template_context = {"repo_path": repo_path}
    mcp_server_names: list[str] = [server["name"] for server in mcp_servers]
    mcp_config = {"mcpServers": dict(map(lambda s: _build_server_entry(s, template_context), mcp_servers))}

    logger.info(f"Using MCP servers: {mcp_server_names}")

    return json.dumps(mcp_config, separators=(",", ":")), mcp_server_names
