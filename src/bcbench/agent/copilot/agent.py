"""GitHub Copilot CLI Agent implementation."""

import subprocess
from pathlib import Path

from bcbench.agent.copilot.cli import invoke_copilot
from bcbench.agent.settings import AgentSettings
from bcbench.agent.shared import (
    agent_subprocess_env,
    build_al_lsp_plugin,
    build_mcp_config,
    resolve_config_plugins,
    start_bc_mcp_gateway,
)
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.operations import setup_agent_skills, setup_custom_agent, setup_instructions_from_config
from bcbench.types import AgentHarness, AgentMetrics, AgentRuntimeConfig, EvaluationCategory, ExperimentConfiguration, PluginConfig

logger = get_logger(__name__)


def run_copilot_agent(
    entry: BaseDatasetEntry,
    model: str,
    category: EvaluationCategory,
    repo_path: Path,
    output_dir: Path,
    runtime: AgentRuntimeConfig | None = None,
    *,
    settings: AgentSettings,
    prompt: str,
    pass_bc_credentials: bool,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    """Run GitHub Copilot CLI agent on a single dataset entry.

    Returns:
        Tuple of (AgentMetrics, ExperimentConfiguration) with metrics and configuration used during the experiment
    """
    copilot_config = settings.shared_config

    logger.info(f"Running GitHub Copilot CLI on: {entry.instance_id}")

    bc_gateway = start_bc_mcp_gateway(runtime)
    mcp_config_json, mcp_server_names = build_mcp_config(
        copilot_config,
        entry,
        repo_path,
        runtime=runtime,
        bc_mcp_gateway_url=bc_gateway.base_url if bc_gateway else None,
        settings=settings,
    )
    lsp_plugin_dir: Path | None = build_al_lsp_plugin(
        entry,
        category,
        repo_path,
        AgentHarness.COPILOT,
        runtime=runtime,
        settings=settings,
    )
    instructions_enabled: bool = setup_instructions_from_config(
        copilot_config, entry, repo_path, harness=AgentHarness.COPILOT, instructions_root=settings.instructions_root, instruction_source_naming=settings.instruction_source_naming
    )
    skills_enabled: bool = setup_agent_skills(copilot_config, entry, repo_path, harness=AgentHarness.COPILOT, instructions_root=settings.instructions_root)
    custom_agent: str | None = setup_custom_agent(copilot_config, entry, repo_path, harness=AgentHarness.COPILOT, instructions_root=settings.instructions_root)
    plugins: list[tuple[PluginConfig, Path]] = resolve_config_plugins(copilot_config, settings=settings, allow_copilot_manifest=True)

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
        extra_args = [
            "--log-level=debug",
            f"--log-dir={output_dir.resolve()}",
        ]
        if mcp_config_json:
            extra_args.append(f"--additional-mcp-config={mcp_config_json}")
        if lsp_plugin_dir is not None:
            extra_args.append(f"--plugin-dir={lsp_plugin_dir}")
        extra_args.extend(f"--plugin-dir={plugin_dir}" for _, plugin_dir in plugins)
        # --add-dir grants read+write (unlike --plugin-dir, which only registers a plugin), so hand it
        # only to plugins that opt in via grant_dir_access - currently a temporary accommodation for
        # BCQuality, whose skill reads its own knowledge files at runtime. Enabling a plugin must not
        # silently widen the agent's sandbox access.
        extra_args.extend(f"--add-dir={plugin_dir}" for plugin, plugin_dir in plugins if plugin.grant_dir_access)
        if custom_agent:
            extra_args.append(f"--agent={custom_agent}")

        metrics, _ = invoke_copilot(
            prompt=prompt,
            model=model,
            work_dir=repo_path,
            timeout=settings.timeout,
            executable=settings.copilot_executable,
            allow_all_tools=True,
            custom_instructions=instructions_enabled,
            extra_args=extra_args,
            env=agent_subprocess_env(
                settings.environment,
                {
                    "GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": "true",
                },
                pass_bc_credentials=pass_bc_credentials,
            ),
        )
        logger.info(f"Copilot CLI run complete for: {entry.instance_id}")
    except subprocess.TimeoutExpired:
        logger.exception(f"Copilot CLI timed out after {settings.timeout} seconds")
        metrics = AgentMetrics(execution_time=settings.timeout)
        raise AgentTimeoutError("Copilot CLI timed out", metrics=metrics, config=config) from None
    except subprocess.CalledProcessError as e:
        logger.exception(f"Copilot CLI execution failed with error {e.stderr}")
        raise AgentError(f"Copilot CLI execution failed: {e}") from None
    except Exception:
        logger.exception("Unexpected error running Copilot CLI")
        raise
    else:
        return metrics, config
    finally:
        if bc_gateway is not None:
            bc_gateway.stop()
