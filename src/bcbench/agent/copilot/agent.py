"""GitHub Copilot CLI Agent implementation."""

import subprocess
from contextlib import ExitStack
from pathlib import Path

import yaml

from bcbench.agent.copilot.cli import invoke_copilot
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
from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.operations import setup_agent_skills, setup_custom_agent, setup_instructions_from_config
from bcbench.types import AgentHarness, AgentMetrics, AgentRuntimeConfig, EvaluationCategory, ExperimentConfiguration, PluginConfig

logger = get_logger(__name__)
_config = get_config()


def run_copilot_agent(
    entry: BaseDatasetEntry,
    model: str,
    category: EvaluationCategory,
    repo_path: Path,
    output_dir: Path,
    runtime: AgentRuntimeConfig | None = None,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    """Run GitHub Copilot CLI agent on a single dataset entry.

    Returns:
        Tuple of (AgentMetrics, ExperimentConfiguration) with metrics and configuration used during the experiment
    """
    config_file = Path(__file__).parent.parent / "shared" / "config.yaml"
    copilot_config = yaml.safe_load(config_file.read_text())

    logger.info(f"Running GitHub Copilot CLI on: {entry.instance_id}")

    history_settings = resolve_history_settings(copilot_config, category)
    prompt: str = build_prompt(entry, repo_path, copilot_config, category, al_mcp=bool(runtime and runtime.al_mcp), history=history_settings)
    lsp_plugin_dir: Path | None = build_al_lsp_plugin(
        entry,
        category,
        repo_path,
        AgentHarness.COPILOT,
        runtime=runtime,
    )
    instructions_enabled: bool = setup_instructions_from_config(copilot_config, entry, repo_path, harness=AgentHarness.COPILOT)
    skills_enabled: bool = setup_agent_skills(copilot_config, entry, repo_path, harness=AgentHarness.COPILOT)
    custom_agent: str | None = setup_custom_agent(copilot_config, entry, repo_path, harness=AgentHarness.COPILOT)
    plugins: list[tuple[PluginConfig, Path]] = resolve_config_plugins(copilot_config, allow_copilot_manifest=True)

    config = ExperimentConfiguration(
        al_lsp_enabled=lsp_plugin_dir is not None,
        custom_instructions=instructions_enabled,
        skills_enabled=skills_enabled,
        custom_agent=custom_agent,
        plugins=[plugin.record for plugin, _ in plugins] or None,
        history=history_settings,
    )

    logger.info(f"Executing Copilot CLI in directory: {repo_path}")
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
                copilot_config,
                entry,
                repo_path,
                runtime=runtime,
                bc_mcp_gateway_url=bc_gateway.base_url if bc_gateway else None,
                history_gateway_url=history_gateway.base_url if history_gateway else None,
            )
            config = config.model_copy(update={"mcp_servers": mcp_server_names})
            extra_args = [
                "--log-level=debug",
                f"--log-dir={output_dir.resolve()}",
            ]
            if mcp_config_json:
                extra_args.append(f"--additional-mcp-config={mcp_config_json}")
            if lsp_plugin_dir is not None:
                extra_args.append(f"--plugin-dir={lsp_plugin_dir}")
            extra_args.extend(f"--plugin-dir={plugin_dir}" for _, plugin_dir in plugins)
            # Directory access is opt-in; registering a plugin must not widen filesystem access.
            extra_args.extend(f"--add-dir={plugin_dir}" for plugin, plugin_dir in plugins if plugin.grant_dir_access)
            if custom_agent:
                extra_args.append(f"--agent={custom_agent}")

            metrics, _ = invoke_copilot(
                prompt=prompt,
                model=model,
                work_dir=repo_path,
                timeout=_config.timeout.agent_execution,
                allow_all_tools=True,
                custom_instructions=instructions_enabled,
                extra_args=extra_args,
                env=agent_subprocess_env(
                    {
                        "GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": "true",
                    },
                    pass_bc_credentials=category.pass_on_bc_container_credentials,
                ),
            )
            logger.info(f"Copilot CLI run complete for: {entry.instance_id}")
    except subprocess.TimeoutExpired:
        logger.exception(f"Copilot CLI timed out after {_config.timeout.agent_execution} seconds")
        metrics = attach_history_metrics(AgentMetrics(execution_time=_config.timeout.agent_execution), history_gateway)
        raise AgentTimeoutError("Copilot CLI timed out", metrics=metrics, config=config) from None
    except subprocess.CalledProcessError as e:
        logger.exception(f"Copilot CLI execution failed with error {e.stderr}")
        raise AgentError(f"Copilot CLI execution failed: {e}") from None
    except Exception:
        logger.exception("Unexpected error running Copilot CLI")
        raise
    else:
        return attach_history_metrics(metrics, history_gateway), config
