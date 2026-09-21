import shutil
import subprocess
from pathlib import Path

import yaml

from bcbench.agent.claude.metrics import parse_stream_output
from bcbench.agent.shared import (
    agent_subprocess_env,
    build_al_lsp_plugin,
    build_mcp_config,
    build_prompt,
    resolve_config_plugins,
    start_bc_mcp_gateway,
)
from bcbench.agent.shared.contained_process import (
    AgentExecutionPolicy,
    ContainedProcessInfrastructureError,
    ContainedProcessRequest,
    run_contained_process,
    should_log_transcript,
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
    execution_policy: AgentExecutionPolicy | None = None,
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

    prompt: str = build_prompt(entry, repo_path, claude_config, category, al_mcp=bool(runtime and runtime.al_mcp))
    managed_clients = execution_policy.managed_clients if execution_policy else None
    bc_gateway = start_bc_mcp_gateway(runtime, register=managed_clients.register) if managed_clients is not None else start_bc_mcp_gateway(runtime)
    try:
        mcp_config_json, mcp_server_names = build_mcp_config(
            claude_config,
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
            AgentHarness.CLAUDE,
            runtime=runtime,
            plugin_root=execution_policy.plugin_root if execution_policy else None,
        )
        instructions_enabled: bool = setup_instructions_from_config(claude_config, entry, repo_path, harness=AgentHarness.CLAUDE)
        skills_enabled: bool = setup_agent_skills(claude_config, entry, repo_path, harness=AgentHarness.CLAUDE)
        custom_agent: str | None = setup_custom_agent(claude_config, entry, repo_path, harness=AgentHarness.CLAUDE)
        plugins: list[tuple[PluginConfig, Path]] = resolve_config_plugins(claude_config, allow_copilot_manifest=False, plugin_root=execution_policy.plugin_root if execution_policy else None)

        config = ExperimentConfiguration(
            mcp_servers=mcp_server_names,
            al_lsp_enabled=lsp_plugin_dir is not None,
            custom_instructions=instructions_enabled,
            skills_enabled=skills_enabled,
            custom_agent=custom_agent,
            plugins=[plugin.record for plugin, _ in plugins] or None,
        )

        logger.info(f"Executing Claude Code in directory: {repo_path}")
        logger.debug("Claude Code prompt prepared: character_count=%d", len(prompt))

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

            logger.debug(
                "Claude Code invocation: executable=%s model=%s mcp_servers=%s al_lsp=%s custom_instructions=%s skills=%s plugins=%d additional_dirs=%d custom_agent=%s prompt_chars=%d",
                claude_cmd,
                model,
                mcp_server_names or [],
                lsp_plugin_dir is not None,
                instructions_enabled,
                skills_enabled,
                len(plugins),
                sum(plugin.grant_dir_access for plugin, _ in plugins),
                custom_agent is not None,
                len(prompt),
            )

            env = agent_subprocess_env(
                {
                    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
                    # A cold BC MCP startup can take ~45s, beyond Claude's 30s default.
                    "MCP_TIMEOUT": "180000",
                    # BaseApp publishing takes many minutes; premature cancellation can leave apps uninstalled.
                    "MCP_TOOL_TIMEOUT": str(_config.timeout.build_baseapp * 1000) if runtime and runtime.al_mcp else "180000",
                },
                pass_bc_credentials=category.pass_on_bc_container_credentials,
                allowlist=bool(execution_policy and execution_policy.contain_process_tree and execution_policy.allowlist_environment),
                final_overrides=execution_policy.environment_overrides if execution_policy is not None else None,
            )
            if execution_policy is not None and execution_policy.contain_process_tree:
                try:
                    contained_result = run_contained_process(
                        ContainedProcessRequest(
                            command=tuple(cmd_args),
                            cwd=repo_path,
                            env=env,
                            timeout_seconds=_config.timeout.agent_execution,
                            identity=execution_policy.restricted_identity,
                            python_executable=execution_policy.python_executable,
                            worker_path=execution_policy.worker_path,
                            worker_sha256=execution_policy.worker_sha256,
                        )
                    )
                except subprocess.CalledProcessError as exc:
                    raise ContainedProcessInfrastructureError.from_called_process_error(exc) from exc
                result = subprocess.CompletedProcess(
                    args=cmd_args,
                    returncode=contained_result.returncode,
                    stdout=contained_result.stdout,
                    stderr=contained_result.stderr,
                )
                result.check_returncode()
            else:
                result = subprocess.run(
                    cmd_args,
                    cwd=str(repo_path),
                    env=env,
                    timeout=_config.timeout.agent_execution,
                    check=True,
                    capture_output=True,
                )

            stdout: str = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else result.stdout or ""
            logger.debug("Claude Code output received: character_count=%d line_count=%d", len(stdout), len(stdout.splitlines()))

            metrics, _ = parse_stream_output(
                stdout.splitlines(),
                log_transcript=should_log_transcript(execution_policy),
            )
        except subprocess.TimeoutExpired as exc:
            logger.error(  # noqa: TRY400 - traceback can expose sensitive command arguments
                "Claude Code timed out after %d seconds; stdout_chars=%d stderr_chars=%d",
                _config.timeout.agent_execution,
                len(exc.output or b""),
                len(exc.stderr or b""),
            )
            metrics = AgentMetrics(execution_time=_config.timeout.agent_execution)
            raise AgentTimeoutError(
                "Claude Code timed out",
                metrics=metrics,
                config=config,
                stdout=exc.output,
                stderr=exc.stderr,
            ) from None
        except subprocess.CalledProcessError as e:
            logger.error(  # noqa: TRY400 - traceback can expose sensitive command arguments
                "Claude Code exited with status %d; stdout_chars=%d stderr_chars=%d",
                e.returncode,
                len(e.output or b""),
                len(e.stderr or b""),
            )
            raise AgentError(f"Claude Code exited with status {e.returncode}") from None
        except Exception:
            logger.exception("Unexpected error running Claude Code")
            raise
        else:
            return metrics, config
    finally:
        if bc_gateway is not None and managed_clients is None:
            bc_gateway.stop()
