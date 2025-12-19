import atexit
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from jinja2 import Template

from bcbench.dataset import DatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)


class _ALMcpServerManager:
    """Manages the lifecycle of the AL MCP server process."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None

    def launch(self, projects: str) -> None:
        logger.info("Launching AL MCP server tool...")
        logger.debug(f"Project paths for AL MCP server: {projects}")
        # https://www.nuget.org/packages/Microsoft.Dynamics.BusinessCentral.Development.Tools/#readme-body-tab
        self._process = subprocess.Popen(["al", "LaunchMcpServer", "--projects", projects])
        atexit.register(self.cleanup)
        logger.info("Waiting 60 seconds for MCP server to start...")
        time.sleep(60)

    def cleanup(self) -> None:
        if self._process is not None and self._process.poll() is None:
            logger.info("Terminating AL MCP server...")
            self._process.terminate()
        self._process = None


_mcp_server_manager = _ALMcpServerManager()


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


def build_mcp_config(copilot_config: dict[str, Any], entry: DatasetEntry, repo_path: Path, al_mcp: bool = False) -> tuple[str | None, list[str] | None]:
    # following docs: https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/use-copilot-agents/coding-agent/extend-coding-agent-with-mcp
    mcp_servers: list[dict[str, Any]] = copilot_config.get("mcp", {}).get("servers", [])

    # Handle AL MCP server (special-cased, flag-gated)
    if al_mcp:
        al_mcp_config: dict[str, Any] | None = copilot_config.get("al-mcp")
        if not al_mcp_config:
            raise AgentError("--al-mcp flag enabled but 'al-mcp' section not found in config.yaml")
        mcp_servers = [*mcp_servers, al_mcp_config]
        logger.info("AL MCP server enabled via --al-mcp flag")

    if not mcp_servers:
        return None, None

    template_context = {"repo_path": repo_path}
    mcp_server_names: list[str] = [server["name"] for server in mcp_servers]
    mcp_config = {"mcpServers": dict(map(lambda s: _build_server_entry(s, template_context), mcp_servers))}

    if al_mcp:
        # Launch MCP server with all project paths separated by semicolons
        all_projects = ";".join(str(repo_path / project_path) for project_path in entry.project_paths)
        _mcp_server_manager.launch(all_projects)

    logger.info(f"Using MCP servers: {mcp_server_names}")
    logger.debug(f"MCP configuration: {json.dumps(mcp_config, indent=2)}")

    return json.dumps(mcp_config, separators=(",", ":")), mcp_server_names
