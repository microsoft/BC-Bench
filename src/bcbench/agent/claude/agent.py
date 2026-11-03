import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import override

from bcbench_core.agent.customization import setup_custom_agent, setup_instructions, setup_skills
from bcbench_core.agent.experiment import ExperimentConfiguration
from bcbench_core.agent.harness import AgentIdentity, AgentRequest, AgentResult, Harness
from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.agent.version import get_cli_version
from bcbench_core.exceptions import AgentError, AgentTimeoutError

from bcbench.agent.claude.metrics import parse_stream_output
from bcbench.agent.shared import (
    agent_subprocess_env,
    build_al_lsp_plugin,
    build_mcp_config,
    build_prompt,
    resolve_config_plugins,
    start_bc_mcp_gateway,
)
from bcbench.dataset import BaseDatasetEntry
from bcbench.operations import instructions_profile_dir
from bcbench.types import AgentConfig, AgentHarness, AgentRuntimeConfig, EvaluationCategory, PluginConfig

logger = logging.getLogger(__name__)


def get_claude_version() -> str:
    return get_cli_version(shutil.which("claude"), "Claude Code")


@dataclass(frozen=True)
class ClaudeHarness(Harness[BaseDatasetEntry, AgentHarness]):
    """Claude Code on any category, customized through the agent config."""

    model: str
    category: EvaluationCategory
    agent_config: AgentConfig
    plugin_root: Path
    runtime: AgentRuntimeConfig | None = None
    timeout: int = 60 * 60

    @override
    def identity(self) -> AgentIdentity[AgentHarness]:
        return AgentIdentity[AgentHarness](harness=AgentHarness.CLAUDE, version=get_claude_version(), model=self.model)

    @override
    def run(self, request: AgentRequest[BaseDatasetEntry], /) -> AgentResult:
        entry, repo_path, timeout = request.task, request.work_dir, request.timeout or self.timeout
        model, category, agent_config, plugin_root, runtime = self.model, self.category, self.agent_config, self.plugin_root, self.runtime
        claude_cmd = shutil.which("claude")
        if not claude_cmd:
            raise AgentError("Claude Code not found in PATH. Please ensure it is installed and available.")

        logger.info(f"Running Claude Code on: {entry.instance_id}")

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
            AgentHarness.CLAUDE,
            plugin_root,
            runtime=runtime,
        )
        profile_dir: Path = instructions_profile_dir(entry.customization_profile)
        target_dir: Path = AgentHarness.CLAUDE.get_target_dir(repo_path)
        instructions_enabled: bool = setup_instructions(agent_config.instructions, profile_dir, target_dir, AgentHarness.CLAUDE.instruction_filename)
        skills_enabled: bool = setup_skills(agent_config.skills, profile_dir, target_dir)
        custom_agent: str | None = setup_custom_agent(agent_config.agents, profile_dir, target_dir)
        plugins: list[tuple[PluginConfig, Path]] = resolve_config_plugins(agent_config, plugin_root, allow_copilot_manifest=False)

        config = ExperimentConfiguration(
            mcp_servers=mcp_server_names,
            al_lsp_enabled=lsp_plugin_dir is not None,
            custom_instructions=instructions_enabled,
            skills_enabled=skills_enabled,
            custom_agent=custom_agent,
            plugins=[plugin.record for plugin, _ in plugins] or None,
        )

        logger.info(f"Executing Claude Code in directory: {repo_path}")
        logger.debug(f"Using prompt:\n{prompt}")

        try:
            cmd_args = [
                claude_cmd,
                "--output-format=stream-json",  # emit every event (incl. tool_use, session init) as JSONL
                "--verbose",  # required for stream-json in --print mode
                "--strict-mcp-config",  # Only use MCP servers from --mcp-config, ignoring all other MCP configurations
                "--setting-sources=project,local",
                f"--model={model}",
                "--permission-mode=bypassPermissions",  # bypassPermissions is needed to use tools and mcp servers
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
            # --add-dir grants read+write (unlike --plugin-dir, which only registers a plugin), so hand it
            # only to plugins that opt in via grant_dir_access - currently a temporary accommodation for
            # BCQuality, whose skill reads its own knowledge files at runtime. Enabling a plugin must not
            # silently widen the agent's sandbox access.
            cmd_args.extend(f"--add-dir={plugin_dir}" for plugin, plugin_dir in plugins if plugin.grant_dir_access)
            if custom_agent:
                cmd_args.append(f"--agent={custom_agent}")
            cmd_args.extend(
                [
                    "--print",  # Non-interactive mode
                    prompt.replace("\r", "").replace("\n", " "),
                ]
            )

            logger.debug(f"Claude Code command args: {cmd_args}")

            result = subprocess.run(
                cmd_args,
                cwd=str(repo_path),
                env=agent_subprocess_env(
                    {
                        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
                        # BC MCP's first tools/list compiles the tool catalog and can take ~45s on a cold
                        # container, well past Claude's 30s default MCP startup timeout -> the server is
                        # marked "failed" and its tools never register. Raise both the connection and tool
                        # execution timeouts so the slow first response is tolerated.
                        "MCP_TIMEOUT": "180000",
                        "MCP_TOOL_TIMEOUT": "180000",
                    },
                    pass_bc_credentials=category.pass_on_bc_container_credentials,
                ),
                timeout=timeout,
                check=True,
                capture_output=True,
            )

            stdout: str = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
            logger.debug(f"Claude Code raw output: {stdout}")

            metrics, response = parse_stream_output(stdout.splitlines(), log_transcript=True)
        except subprocess.TimeoutExpired:
            logger.exception(f"Claude Code timed out after {timeout} seconds")
            metrics = AgentMetrics(execution_time=timeout)
            raise AgentTimeoutError("Claude Code timed out", metrics=metrics, config=config) from None
        except subprocess.CalledProcessError as e:
            logger.exception(f"Claude Code execution failed with error {e.stderr}")
            raise AgentError(f"Claude Code execution failed: {e.stderr}") from e
        except Exception:
            logger.exception("Unexpected error running Claude Code")
            raise
        else:
            return AgentResult(response=response, metrics=metrics, experiment=config)
        finally:
            if bc_gateway is not None:
                bc_gateway.stop()
