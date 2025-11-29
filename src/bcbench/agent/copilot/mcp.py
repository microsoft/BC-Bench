import atexit
import json
import subprocess
import time
from pathlib import Path

from jinja2 import Template

from bcbench.dataset import DatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.operations.project_operations import categorize_projects

logger = get_logger(__name__)

_mcp_server_process: subprocess.Popen | None = None


def build_mcp_config(copilot_config: dict, entry: DatasetEntry, repo_path: Path) -> tuple[str | None, list[str] | None]:
    # following docs: https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/use-copilot-agents/coding-agent/extend-coding-agent-with-mcp
    mcp_servers: list[dict] = copilot_config.get("mcp", {}).get("servers", [])
    if not mcp_servers:
        return None, None

    mcp_config = {"mcpServers": {}}
    _test_projects, app_projects = categorize_projects(entry.project_paths)
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

    if "altool" in mcp_server_names:
        _install_and_launch_al_mcp_server(repo_path / app_projects[0])

    logger.info(f"Using MCP servers: {mcp_server_names}")
    logger.debug(f"MCP configuration: {json.dumps(mcp_config, indent=2)}")

    return json.dumps(mcp_config, separators=(",", ":")), mcp_server_names


def _install_and_launch_al_mcp_server(project_path: Path) -> None:
    global _mcp_server_process  # noqa: PLW0603

    logger.info("Installing AL MCP server tool...")
    subprocess.run("dotnet tool install Microsoft.Dynamics.BusinessCentral.Development.Tools --prerelease --global", check=True)

    logger.info("Launching AL MCP server tool...")
    _mcp_server_process = subprocess.Popen(f"al LaunchMcpServer --projects {project_path}")

    atexit.register(_cleanup_mcp_server)

    logger.info("Waiting 5 seconds for MCP server to start...")
    time.sleep(5)


def _cleanup_mcp_server() -> None:
    global _mcp_server_process  # noqa: PLW0603
    if _mcp_server_process is not None and _mcp_server_process.poll() is None:
        logger.info("Terminating AL MCP server...")
        _mcp_server_process.terminate()
    _mcp_server_process = None
