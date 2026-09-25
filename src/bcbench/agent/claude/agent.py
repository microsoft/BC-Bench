import shutil
import subprocess
from contextlib import ExitStack
from pathlib import Path

import yaml

from bcbench.agent.claude.metrics import parse_stream_output
from bcbench.agent.shared import (
    agent_subprocess_env,
    attach_history_metrics,
    build_al_lsp_plugin,
    build_mcp_config,
    build_prompt,
    resolve_config_plugins,
    resolve_history_settings,
    start_bc_mcp_gateway,
    start_history_gateway,
)
from bcbench.agent.shared.version import get_cli_version
from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.operations import setup_agent_skills, setup_custom_agent, setup_instructions_from_config
from bcbench.types import AgentHarness, AgentMetrics, AgentRuntimeConfig, EvaluationCategory, ExperimentConfiguration, PluginConfig

logger = get_logger(__name__)
_config = get_config()


def get_claude_version() -> str:
    return get_cli_version(shutil.which("claude"), "Claude Code")


def run_claude_code(
    entry: BaseDatasetEntry,
    model: str,
    category: EvaluationCategory,
    repo_path: Path,
    output_dir: Path,
    runtime: AgentRuntimeConfig | None = None,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    """Run Claude Code on a single dataset entry.

    Returns:
        Tuple of (AgentMetrics, ExperimentConfiguration) with metrics and configuration used
    """
    config_file = Path(__file__).parent.parent / "shared" / "config.yaml"
    claude_config = yaml.safe_load(config_file.read_text())

    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        raise AgentError("Claude Code not found in PATH. Please ensure it is installed and available.")

    logger.info(f"Running Claude Code on: {entry.instance_id}")

    history_settings = resolve_history_settings(claude_config, category)
    prompt: str = build_prompt(entry, repo_path, claude_config, category, al_mcp=bool(runtime and runtime.al_mcp), history=history_settings)
    lsp_plugin_dir: Path | None = build_al_lsp_plugin(
        entry,
        category,
        repo_path,
        AgentHarness.CLAUDE,
        runtime=runtime,
    )
    instructions_enabled: bool = setup_instructions_from_config(claude_config, entry, repo_path, harness=AgentHarness.CLAUDE)
    skills_enabled: bool = setup_agent_skills(claude_config, entry, repo_path, harness=AgentHarness.CLAUDE)
    custom_agent: str | None = setup_custom_agent(claude_config, entry, repo_path, harness=AgentHarness.CLAUDE)
    plugins: list[tuple[PluginConfig, Path]] = resolve_config_plugins(claude_config, allow_copilot_manifest=False)

    config = ExperimentConfiguration(
        al_lsp_enabled=lsp_plugin_dir is not None,
        custom_instructions=instructions_enabled,
        skills_enabled=skills_enabled,
        custom_agent=custom_agent,
        plugins=[plugin.record for plugin, _ in plugins] or None,
        history=history_settings,
    )

    logger.info(f"Executing Claude Code in directory: {repo_path}")
    logger.debug(f"Using prompt:\n{prompt}")

    history_gateway = None
    try:
        with ExitStack() as cleanup:
            bc_gateway = start_bc_mcp_gateway(runtime)
            if bc_gateway is not None:
                cleanup.callback(bc_gateway.stop)
            history_gateway = start_history_gateway(entry, history_settings, output_dir)
            if history_gateway is not None:
                cleanup.callback(history_gateway.stop)
            mcp_config_json, mcp_server_names = build_mcp_config(
                claude_config,
                entry,
                repo_path,
                runtime=runtime,
                bc_mcp_gateway_url=bc_gateway.base_url if bc_gateway else None,
                history_gateway_url=history_gateway.base_url if history_gateway else None,
            )
            config = config.model_copy(update={"mcp_servers": mcp_server_names})
            cmd_args = [
                claude_cmd,
                "--output-format=stream-json",
                "--verbose",
                "--strict-mcp-config",
                "--setting-sources=project,local",
                f"--model={model}",
                "--permission-mode=bypassPermissions",
                "--disallowedTools",
                "WebFetch",
                "Bash(curl *)",
                "Bash(wget *)",
            ]
            if mcp_config_json:
                cmd_args.append(f"--mcp-config={mcp_config_json}")
            if lsp_plugin_dir is not None:
                cmd_args.append(f"--plugin-dir={lsp_plugin_dir}")
            cmd_args.extend(f"--plugin-dir={plugin_dir}" for _, plugin_dir in plugins)
            # Directory access is opt-in; registering a plugin must not widen filesystem access.
            cmd_args.extend(f"--add-dir={plugin_dir}" for plugin, plugin_dir in plugins if plugin.grant_dir_access)
            if custom_agent:
                cmd_args.append(f"--agent={custom_agent}")
            cmd_args.extend(["--print", prompt.replace("\r", "").replace("\n", " ")])

            logger.debug(f"Claude Code command args: {cmd_args}")
            result = subprocess.run(
                cmd_args,
                cwd=str(repo_path),
                env=agent_subprocess_env(
                    {
                        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
                        # Allow BC's cold tool catalog initialization to exceed the client's default.
                        "MCP_TIMEOUT": "180000",
                        "MCP_TOOL_TIMEOUT": "180000",
                    },
                    pass_bc_credentials=category.pass_on_bc_container_credentials,
                ),
                timeout=_config.timeout.agent_execution,
                check=True,
                capture_output=True,
            )

            stdout: str = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
            logger.debug(f"Claude Code raw output: {stdout}")
            metrics, _ = parse_stream_output(stdout.splitlines(), log_transcript=True)
    except subprocess.TimeoutExpired:
        logger.exception(f"Claude Code timed out after {_config.timeout.agent_execution} seconds")
        metrics = attach_history_metrics(AgentMetrics(execution_time=_config.timeout.agent_execution), history_gateway)
        raise AgentTimeoutError("Claude Code timed out", metrics=metrics, config=config) from None
    except subprocess.CalledProcessError as e:
        logger.exception(f"Claude Code execution failed with error {e.stderr}")
        raise AgentError(f"Claude Code execution failed: {e.stderr}") from e
    except Exception:
        logger.exception("Unexpected error running Claude Code")
        raise
    else:
        return attach_history_metrics(metrics, history_gateway), config
