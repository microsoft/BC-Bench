"""GitHub Copilot CLI Agent implementation."""

import logging
from pathlib import Path

from bcbench_core.agent.copilot import CopilotOptions, CopilotTimeoutError, invoke_copilot
from bcbench_core.agent.customization import setup_custom_agent, setup_instructions, setup_skills
from bcbench_core.agent.metrics import AgentMetrics

from bcbench.agent.shared import (
    agent_subprocess_env,
    build_al_lsp_plugin,
    build_mcp_config,
    build_prompt,
    resolve_config_plugins,
    start_bc_mcp_gateway,
)
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentTimeoutError
from bcbench.operations import instructions_profile_dir
from bcbench.types import AgentConfig, AgentHarness, AgentRuntimeConfig, EvaluationCategory, ExperimentConfiguration, PluginConfig

logger = logging.getLogger(__name__)


def run_copilot_agent(
    entry: BaseDatasetEntry,
    model: str,
    category: EvaluationCategory,
    repo_path: Path,
    output_dir: Path,
    agent_config: AgentConfig,
    plugin_root: Path,
    runtime: AgentRuntimeConfig | None = None,
    timeout: int = 60 * 60,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    """Run GitHub Copilot CLI agent on a single dataset entry.

    Returns:
        Tuple of (AgentMetrics, ExperimentConfiguration) with metrics and configuration used during the experiment
    """
    logger.info(f"Running GitHub Copilot CLI on: {entry.instance_id}")

    prompt: str = build_prompt(entry, repo_path, agent_config, category, al_mcp=bool(runtime and runtime.al_mcp))
    bc_gateway = start_bc_mcp_gateway(runtime)
    mcp_config_json, mcp_server_names = build_mcp_config(
        agent_config,
        entry,
        repo_path,
        runtime=runtime,
        bc_mcp_gateway_url=bc_gateway.base_url if bc_gateway else None,
    )
    lsp_plugin_dir: Path | None = build_al_lsp_plugin(
        entry,
        category,
        repo_path,
        AgentHarness.COPILOT,
        plugin_root,
        runtime=runtime,
    )
    profile_dir: Path = instructions_profile_dir(entry.customization_profile)
    target_dir: Path = AgentHarness.COPILOT.get_target_dir(repo_path)
    instructions_enabled: bool = setup_instructions(agent_config.instructions, profile_dir, target_dir, AgentHarness.COPILOT.instruction_filename)
    skills_enabled: bool = setup_skills(agent_config.skills, profile_dir, target_dir)
    custom_agent: str | None = setup_custom_agent(agent_config.agents, profile_dir, target_dir)
    plugins: list[tuple[PluginConfig, Path]] = resolve_config_plugins(agent_config, plugin_root, allow_copilot_manifest=True)

    config = ExperimentConfiguration(
        mcp_servers=mcp_server_names,
        al_lsp_enabled=lsp_plugin_dir is not None,
        custom_instructions=instructions_enabled,
        skills_enabled=skills_enabled,
        custom_agent=custom_agent,
        plugins=[plugin.record for plugin, _ in plugins] or None,
    )

    try:
        lsp_plugin_dirs = (lsp_plugin_dir,) if lsp_plugin_dir is not None else ()
        # --add-dir grants read+write (unlike --plugin-dir, which only registers a plugin), so hand it
        # only to plugins that opt in via grant_dir_access - currently a temporary accommodation for
        # BCQuality, whose skill reads its own knowledge files at runtime. Enabling a plugin must not
        # silently widen the agent's sandbox access.
        options = CopilotOptions(
            allow_all_tools=True,
            custom_instructions=instructions_enabled,
            log_dir=output_dir,
            mcp_config_json=mcp_config_json,
            plugin_dirs=(*lsp_plugin_dirs, *(plugin_dir for _, plugin_dir in plugins)),
            granted_dirs=tuple(plugin_dir for plugin, plugin_dir in plugins if plugin.grant_dir_access),
            custom_agent=custom_agent,
            workspace_mcp=True,
        )

        metrics, _ = invoke_copilot(
            prompt=prompt,
            model=model,
            work_dir=repo_path,
            timeout=timeout,
            env=agent_subprocess_env(pass_bc_credentials=category.pass_on_bc_container_credentials),
            options=options,
        )
        logger.info(f"Copilot CLI run complete for: {entry.instance_id}")
    except CopilotTimeoutError as exc:
        raise AgentTimeoutError("Copilot CLI timed out", metrics=exc.metrics, config=config) from exc
    else:
        return metrics, config
    finally:
        if bc_gateway is not None:
            bc_gateway.stop()
