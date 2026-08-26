"""GitHub Copilot CLI Agent implementation."""

import os
import subprocess
import sys
from pathlib import Path

import yaml

from bcbench.agent.copilot.metrics import parse_mcp_server_status, parse_output
from bcbench.agent.shared import build_al_lsp_plugin, build_mcp_config, build_prompt, parse_tool_usage_from_hooks, resolve_config_plugins
from bcbench.config import get_config
from bcbench.copilot_cli import find_copilot
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.operations import setup_agent_skills, setup_custom_agent, setup_hooks, setup_instructions_from_config
from bcbench.types import AgentHarness, AgentMetrics, EvaluationCategory, ExperimentConfiguration, McpServerStatus, PluginConfig

logger = get_logger(__name__)
_config = get_config()


def _log_unavailable_mcp_servers(requested: list[str], observed: list[McpServerStatus]) -> None:
    """Warn when a requested MCP server did not come up.

    The CLI exits 0 and writes nothing to stderr when an MCP server fails, so without this the
    run silently degrades into one that never had the server, while still being recorded as if it did.
    """
    if not observed:
        logger.warning(f"Copilot CLI reported no MCP server status; cannot confirm {requested} loaded")
        return

    by_name = {server.name: server for server in observed}
    for name in requested:
        server = by_name.get(name)
        if server is None:
            logger.warning(f"MCP server '{name}' was requested but never reported by Copilot CLI")
        elif server.status != "connected":
            logger.warning(f"MCP server '{name}' was requested but is '{server.status}'{f': {server.error}' if server.error else ''}")


def run_copilot_agent(
    entry: BaseDatasetEntry,
    model: str,
    category: EvaluationCategory,
    repo_path: Path,
    output_dir: Path,
    al_mcp: bool = False,
    al_lsp: bool = False,
    container_name: str = "bcbench",
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    """Run GitHub Copilot CLI agent on a single dataset entry.

    Returns:
        Tuple of (AgentMetrics, ExperimentConfiguration) with metrics and configuration used during the experiment
    """
    config_file = Path(__file__).parent.parent / "shared" / "config.yaml"
    copilot_config = yaml.safe_load(config_file.read_text())

    # Prefer copilot.exe over copilot.bat/copilot.cmd shims on Windows: the .bat shim invokes PowerShell,
    # which re-parses arguments and corrupts prompts containing double quotes (e.g. JSON examples).
    copilot_cmd = find_copilot()
    if not copilot_cmd:
        raise AgentError("Copilot CLI not found in PATH. Please ensure it is installed and available.")

    logger.info(f"Running GitHub Copilot CLI on: {entry.instance_id}")

    prompt: str = build_prompt(entry, repo_path, copilot_config, category, al_mcp=al_mcp)
    mcp_config_json, mcp_server_names = build_mcp_config(copilot_config, entry, repo_path, al_mcp=al_mcp, container_name=container_name)
    lsp_plugin_dir: Path | None = build_al_lsp_plugin(entry, category, repo_path, AgentHarness.COPILOT, al_lsp=al_lsp, container_name=container_name)
    instructions_enabled: bool = setup_instructions_from_config(copilot_config, entry, repo_path, harness=AgentHarness.COPILOT)
    skills_enabled: bool = setup_agent_skills(copilot_config, entry, repo_path, harness=AgentHarness.COPILOT)
    custom_agent: str | None = setup_custom_agent(copilot_config, entry, repo_path, harness=AgentHarness.COPILOT)
    tool_log_path: Path = setup_hooks(repo_path, AgentHarness.COPILOT, output_dir)
    plugins: list[tuple[PluginConfig, Path]] = resolve_config_plugins(copilot_config, allow_copilot_manifest=True)

    config = ExperimentConfiguration(
        mcp_servers=mcp_server_names,
        al_lsp_enabled=lsp_plugin_dir is not None,
        custom_instructions=instructions_enabled,
        skills_enabled=skills_enabled,
        custom_agent=custom_agent,
        plugins=[plugin.record for plugin, _ in plugins] or None,
    )

    logger.info(f"Executing Copilot CLI in directory: {repo_path}")
    logger.debug(f"Using prompt:\n{prompt}")

    try:
        cmd_args = [
            copilot_cmd,
            "--output-format=json",
            "--allow-all-tools",  # required for non-interactive mode
            "--disable-builtin-mcps",
            f"--model={model}",
            "--log-level=debug",
            f"--log-dir={output_dir.resolve()}",
            f"--prompt={prompt.replace('\r', '').replace('\n', ' ')}",
        ]
        if not instructions_enabled:
            cmd_args.append("--no-custom-instructions")
        if mcp_config_json:
            cmd_args.append(f"--additional-mcp-config={mcp_config_json}")
        if lsp_plugin_dir is not None:
            cmd_args.append(f"--plugin-dir={lsp_plugin_dir}")
        cmd_args.extend(f"--plugin-dir={plugin_dir}" for _, plugin_dir in plugins)
        # --add-dir grants read+write (unlike --plugin-dir, which only registers a plugin), so hand it
        # only to plugins that opt in via grant_dir_access - currently a temporary accommodation for
        # BCQuality, whose skill reads its own knowledge files at runtime. Enabling a plugin must not
        # silently widen the agent's sandbox access.
        cmd_args.extend(f"--add-dir={plugin_dir}" for plugin, plugin_dir in plugins if plugin.grant_dir_access)
        if custom_agent:
            cmd_args.append(f"--agent={custom_agent}")

        logger.debug(f"Copilot command args: {cmd_args}")

        result = subprocess.run(
            cmd_args,
            cwd=str(repo_path),
            env={
                **os.environ,
                "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS": "true",
                "GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": "true",
            },
            capture_output=True,
            timeout=_config.timeout.agent_execution,
            check=True,
        )

        if result.stderr:
            sys.stderr.buffer.write(result.stderr)
            sys.stderr.buffer.flush()
        logger.info(f"Copilot CLI run complete for: {entry.instance_id}")

        stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        output_lines = stdout.splitlines()
        metrics, final_response = parse_output(output_lines)
        if final_response:
            logger.info(final_response)

        mcp_servers_observed = parse_mcp_server_status(output_lines)
        if mcp_server_names:
            _log_unavailable_mcp_servers(mcp_server_names, mcp_servers_observed)

        tool_usage: dict[str, int] | None = parse_tool_usage_from_hooks(tool_log_path)
        if metrics:
            metrics = metrics.model_copy(update={"tool_usage": tool_usage, "mcp_servers_observed": mcp_servers_observed or None})
    except subprocess.TimeoutExpired:
        logger.exception(f"Copilot CLI timed out after {_config.timeout.agent_execution} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.agent_execution)
        raise AgentTimeoutError("Copilot CLI timed out", metrics=metrics, config=config) from None
    except subprocess.CalledProcessError as e:
        logger.exception(f"Copilot CLI execution failed with error {e.stderr}")
        raise AgentError(f"Copilot CLI execution failed: {e}") from None
    except Exception:
        logger.exception("Unexpected error running Copilot CLI")
        raise
    else:
        return metrics, config
