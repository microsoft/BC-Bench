"""GitHub Copilot CLI Agent implementation."""

from pathlib import Path

import yaml
from bcbench_core.agents.copilot import CopilotExtension, CopilotHarness, CopilotSettings, PreparedCopilotExtension
from bcbench_core.evaluation import EvaluationRequest
from bcbench_core.types import AgentMetrics, AgentRuntimeConfig, DatasetEntry, ExperimentConfiguration, PluginConfig

from bcbench.agent.shared import (
    agent_subprocess_env,
    build_al_lsp_plugin,
    build_mcp_config,
    build_prompt,
    resolve_config_plugins,
    start_bc_mcp_gateway,
)
from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.operations import setup_agent_skills, setup_custom_agent, setup_instructions_from_config
from bcbench.types import AgentHarness, EvaluationCategory

logger = get_logger(__name__)
_config = get_config()


class _BCBenchCopilotExtension(CopilotExtension[DatasetEntry]):
    def __init__(
        self,
        *,
        category: EvaluationCategory,
        runtime: AgentRuntimeConfig | None,
        agent_config: dict,
    ) -> None:
        self._category = category
        self._runtime = runtime
        self._agent_config = agent_config
        self._gateway = None

    def prepare(self, request: EvaluationRequest[DatasetEntry]) -> PreparedCopilotExtension:
        entry = request.entry
        self._gateway = start_bc_mcp_gateway(self._runtime)
        mcp_config_json, mcp_server_names = build_mcp_config(
            self._agent_config,
            entry,
            request.repo_path,
            runtime=self._runtime,
            bc_mcp_gateway_url=self._gateway.base_url if self._gateway else None,
        )
        lsp_plugin_dir = build_al_lsp_plugin(
            entry,
            self._category,
            request.repo_path,
            AgentHarness.COPILOT,
            runtime=self._runtime,
        )
        instructions_enabled = setup_instructions_from_config(self._agent_config, entry, request.repo_path, harness=AgentHarness.COPILOT)
        skills_enabled = setup_agent_skills(self._agent_config, entry, request.repo_path, harness=AgentHarness.COPILOT)
        custom_agent = setup_custom_agent(self._agent_config, entry, request.repo_path, harness=AgentHarness.COPILOT)
        plugins: list[tuple[PluginConfig, Path]] = resolve_config_plugins(self._agent_config, allow_copilot_manifest=True)

        arguments = [
            "--log-level=debug",
            f"--log-dir={request.result_dir.resolve()}",
        ]
        if mcp_config_json:
            arguments.append(f"--additional-mcp-config={mcp_config_json}")
        if lsp_plugin_dir is not None:
            arguments.append(f"--plugin-dir={lsp_plugin_dir}")
        arguments.extend(f"--plugin-dir={plugin_dir}" for _, plugin_dir in plugins)
        arguments.extend(f"--add-dir={plugin_dir}" for plugin, plugin_dir in plugins if plugin.grant_dir_access)
        if custom_agent:
            arguments.append(f"--agent={custom_agent}")

        return PreparedCopilotExtension(
            arguments=tuple(arguments),
            mcp_servers=tuple(mcp_server_names or ()),
            al_lsp_enabled=lsp_plugin_dir is not None,
            custom_instructions=instructions_enabled,
            skills_enabled=skills_enabled,
            custom_agent=custom_agent,
            plugins=tuple(plugin.record for plugin, _ in plugins),
        )

    def close(self) -> None:
        if self._gateway is not None:
            self._gateway.stop()
            self._gateway = None


def run_copilot_agent(
    entry: BaseDatasetEntry,
    model: str,
    category: EvaluationCategory,
    repo_path: Path,
    output_dir: Path,
    runtime: AgentRuntimeConfig | None = None,
    prompt: str | None = None,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    """Run GitHub Copilot CLI agent on a single dataset entry.

    Returns:
        Tuple of (AgentMetrics, ExperimentConfiguration) with metrics and configuration used during the experiment
    """
    config_file = Path(__file__).parent.parent / "shared" / "config.yaml"
    copilot_config = yaml.safe_load(config_file.read_text())

    logger.info(f"Running GitHub Copilot CLI on: {entry.instance_id}")
    prompt = prompt or build_prompt(entry, repo_path, copilot_config, category, al_mcp=bool(runtime and runtime.al_mcp))
    harness = CopilotHarness(
        CopilotSettings(
            timeout=_config.timeout.agent_execution,
            pass_environment=agent_subprocess_env(
                {"GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": "true"},
                pass_bc_credentials=category.pass_on_bc_container_credentials,
            ),
        ),
        extensions=(
            _BCBenchCopilotExtension(
                category=category,
                runtime=runtime,
                agent_config=copilot_config,
            ),
        ),
    )
    execution = harness.run(
        EvaluationRequest(
            entry=entry,
            repo_path=repo_path,
            result_dir=output_dir,
            result_file=f"{entry.instance_id}.jsonl",
            model=model,
            prompt=prompt,
        )
    )
    if execution.timed_out:
        raise AgentTimeoutError("Copilot CLI timed out", metrics=execution.metrics, config=execution.experiment)
    logger.info(f"Copilot CLI run complete for: {entry.instance_id}")
    return execution.metrics, execution.experiment
