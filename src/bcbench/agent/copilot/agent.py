"""GitHub Copilot CLI Agent implementation."""

import subprocess
from pathlib import Path

import yaml

from bcbench.agent.copilot.cli import invoke_copilot
from bcbench.agent.shared import (
    agent_subprocess_env,
    build_al_lsp_plugin,
    build_mcp_config,
    build_prompt,
    resolve_config_plugins,
    start_bc_mcp_gateway,
)
from bcbench.agent.shared.contained_process import AgentExecutionPolicy
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
    execution_policy: AgentExecutionPolicy | None = None,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    """Run GitHub Copilot CLI agent on a single dataset entry.

    Returns:
        Tuple of (AgentMetrics, ExperimentConfiguration) with metrics and configuration used during the experiment
    """
    config_file = Path(__file__).parent.parent / "shared" / "config.yaml"
    copilot_config = yaml.safe_load(config_file.read_text())

    logger.info(f"Running GitHub Copilot CLI on: {entry.instance_id}")

    prompt: str = build_prompt(entry, repo_path, copilot_config, category, al_mcp=bool(runtime and runtime.al_mcp))
    managed_clients = execution_policy.managed_clients if execution_policy else None
    bc_gateway = start_bc_mcp_gateway(runtime, register=managed_clients.register) if managed_clients is not None else start_bc_mcp_gateway(runtime)
    try:
        mcp_config_json, mcp_server_names = build_mcp_config(
            copilot_config,
            entry,
            repo_path,
            runtime=runtime,
            bc_mcp_gateway_url=bc_gateway.base_url if bc_gateway else None,
            managed_clients=managed_clients,
            require_evaluator_bridge=bool(execution_policy and execution_policy.restricted_identity),
        )
        lsp_plugin_dir: Path | None = build_al_lsp_plugin(
            entry,
            category,
            repo_path,
            AgentHarness.COPILOT,
            runtime=runtime,
            plugin_root=execution_policy.plugin_root if execution_policy else None,
        )
        instructions_enabled: bool = setup_instructions_from_config(copilot_config, entry, repo_path, harness=AgentHarness.COPILOT)
        skills_enabled: bool = setup_agent_skills(copilot_config, entry, repo_path, harness=AgentHarness.COPILOT)
        custom_agent: str | None = setup_custom_agent(copilot_config, entry, repo_path, harness=AgentHarness.COPILOT)
        plugins: list[tuple[PluginConfig, Path]] = resolve_config_plugins(copilot_config, allow_copilot_manifest=True, plugin_root=execution_policy.plugin_root if execution_policy else None)

        config = ExperimentConfiguration(
            mcp_servers=mcp_server_names,
            al_lsp_enabled=lsp_plugin_dir is not None,
            custom_instructions=instructions_enabled,
            skills_enabled=skills_enabled,
            custom_agent=custom_agent,
            plugins=[plugin.record for plugin, _ in plugins] or None,
        )

        logger.info(f"Executing Copilot CLI in directory: {repo_path}")
        logger.debug("Copilot prompt prepared: character_count=%d", len(prompt))

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
                timeout=_config.timeout.agent_execution,
                allow_all_tools=True,
                custom_instructions=instructions_enabled,
                extra_args=extra_args,
                mcp_server_names=mcp_server_names or (),
                env=agent_subprocess_env(
                    {
                        "GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": "true",
                    },
                    pass_bc_credentials=category.pass_on_bc_container_credentials,
                    allowlist=bool(execution_policy and execution_policy.contain_process_tree and execution_policy.allowlist_environment),
                    final_overrides=execution_policy.environment_overrides if execution_policy is not None else None,
                ),
                execution_policy=execution_policy,
            )
            logger.info(f"Copilot CLI run complete for: {entry.instance_id}")
        except subprocess.TimeoutExpired as exc:
            logger.error(  # noqa: TRY400 - traceback can expose sensitive command arguments
                "Copilot CLI timed out after %d seconds; stdout_chars=%d stderr_chars=%d",
                _config.timeout.agent_execution,
                len(exc.output or b""),
                len(exc.stderr or b""),
            )
            metrics = AgentMetrics(execution_time=_config.timeout.agent_execution)
            raise AgentTimeoutError(
                "Copilot CLI timed out",
                metrics=metrics,
                config=config,
                stdout=exc.output,
                stderr=exc.stderr,
            ) from None
        except subprocess.CalledProcessError as e:
            logger.error(  # noqa: TRY400 - traceback can expose sensitive command arguments
                "Copilot CLI exited with status %d; stdout_chars=%d stderr_chars=%d",
                e.returncode,
                len(e.output or b""),
                len(e.stderr or b""),
            )
            raise AgentError(f"Copilot CLI exited with status {e.returncode}") from None
        except Exception:
            logger.exception("Unexpected error running Copilot CLI")
            raise
        else:
            return metrics, config
    finally:
        if bc_gateway is not None and managed_clients is None:
            bc_gateway.stop()
