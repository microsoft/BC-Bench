import json
from pathlib import Path

from jinja2 import Template

from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)


def build_mcp_config(copilot_config: dict, repo_path: Path) -> tuple[str | None, list[str] | None]:
    # following docs: https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/use-copilot-agents/coding-agent/extend-coding-agent-with-mcp
    mcp_servers: list[dict] = copilot_config.get("mcp", {}).get("servers", [])
    if not mcp_servers:
        return None, None

    mcp_config = {"mcpServers": {}}
    template_context = {"repo_path": repo_path}

    mcp_server_names: list[str] = []
    for server in mcp_servers:
        server_type: str = server["type"]
        server_name: str = server["name"]
        tools: list[str] = server["tools"]

        mcp_server_names.append(server_name)
        match server_type:
            case "http":
                mcp_config["mcpServers"][server_name] = {
                    "type": server_type,
                    "url": server["url"],
                    "tools": tools,
                }
            case "local":
                args: list[str] = server["args"]
                rendered_args = [Template(arg).render(**template_context) for arg in args]

                mcp_config["mcpServers"][server_name] = {
                    "type": server_type,
                    "command": server["command"],
                    "args": rendered_args,
                    "tools": tools,
                }
            case _:
                logger.error(f"Unsupported MCP server type: {server_type}, {server}")
                raise AgentError(f"Unsupported MCP server type: {server_type}")

    logger.info(f"Using MCP servers: {mcp_server_names}")

    return json.dumps(mcp_config, separators=(",", ":")), mcp_server_names
