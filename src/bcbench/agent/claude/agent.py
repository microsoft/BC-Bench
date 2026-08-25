import shutil
import subprocess
from pathlib import Path

import yaml

from bcbench.agent.claude.metrics import parse_stream_output
from bcbench.agent.shared import agent_subprocess_env, build_al_lsp_plugin, build_mcp_config, build_prompt, parse_tool_usage_from_hooks, resolve_config_plugins, start_bc_mcp_gateway
from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.operations import setup_agent_skills, setup_custom_agent, setup_hooks, setup_instructions_from_config
from bcbench.types import AgentHarness, AgentMetrics, EvaluationCategory, ExperimentConfiguration, PluginConfig

logger = get_logger(__name__)
_config = get_config()


def run_claude_code(
    entry: BaseDatasetEntry,
    model: str,
    category: EvaluationCategory,
    repo_path: Path,
    output_dir: Path,
    al_mcp: bool = False,
    al_lsp: bool = False,
    bc_mcp: bool = False,
    ms_learn_mcp: bool = False,
    skills: bool = False,
    container_name: str = "bcbench",
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

    prompt: str = build_prompt(entry, repo_path, claude_config, category, al_mcp=al_mcp)
    bc_gateway = start_bc_mcp_gateway(bc_mcp)
    mcp_config_json, mcp_server_names = build_mcp_config(
        claude_config,
        entry,
        repo_path,
        al_mcp=al_mcp,
        bc_mcp=bc_mcp,
        ms_learn_mcp=ms_learn_mcp,
        container_name=container_name,
        bc_mcp_gateway_url=bc_gateway.base_url if bc_gateway else None,
    )
    lsp_plugin_dir: Path | None = build_al_lsp_plugin(entry, category, repo_path, AgentHarness.CLAUDE, al_lsp=al_lsp, container_name=container_name)
    instructions_enabled: bool = setup_instructions_from_config(claude_config, entry, repo_path, harness=AgentHarness.CLAUDE)
    skills_enabled: bool = setup_agent_skills(claude_config, entry, repo_path, harness=AgentHarness.CLAUDE, skills_enabled_override=skills)
    custom_agent: str | None = setup_custom_agent(claude_config, entry, repo_path, harness=AgentHarness.CLAUDE)
    tool_log_path: Path = setup_hooks(repo_path, AgentHarness.CLAUDE, output_dir)
    plugins: list[tuple[PluginConfig, Path]] = resolve_config_plugins(claude_config, allow_copilot_manifest=False)

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
                }
            ),
            timeout=_config.timeout.agent_execution,
            check=True,
            capture_output=True,
        )

        stdout: str = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        logger.debug(f"Claude Code raw output: {stdout}")

        metrics, final_response = parse_stream_output(stdout.splitlines())
        if final_response:
            logger.info(final_response)

        # The stream's tool_use events capture sub-agent and MCP tool calls; fall back to the pre-tool-use
        # hook only when the stream carried none.
        if metrics and not metrics.tool_usage and (hook_tool_usage := parse_tool_usage_from_hooks(tool_log_path)):
            metrics = metrics.model_copy(update={"tool_usage": hook_tool_usage})
    except subprocess.TimeoutExpired:
        logger.exception(f"Claude Code timed out after {_config.timeout.agent_execution} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.agent_execution)
        raise AgentTimeoutError("Claude Code timed out", metrics=metrics, config=config) from None
    except subprocess.CalledProcessError as e:
        logger.exception(f"Claude Code execution failed with error {e.stderr}")
        raise AgentError(f"Claude Code execution failed: {e.stderr}") from e
    except Exception:
        logger.exception("Unexpected error running Claude Code")
        raise
    else:
        return metrics, config
    finally:
        if bc_gateway is not None:
            bc_gateway.stop()
