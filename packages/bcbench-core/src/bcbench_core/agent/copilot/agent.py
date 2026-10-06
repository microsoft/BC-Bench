import logging
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from bcbench_core.agent.copilot.cli import invoke_copilot as invoke_cli
from bcbench_core.agent.copilot.types import CopilotOptions, CopilotProcessError, CopilotTimeoutError
from bcbench_core.agent.env import agent_subprocess_env
from bcbench_core.agent.metrics import AgentMetrics

logger = logging.getLogger(__name__)


def copilot_session_args(
    log_dir: Path | None = None,
    mcp_config_json: str | None = None,
    plugin_dirs: Sequence[Path] = (),
    granted_dirs: Sequence[Path] = (),
    custom_agent: str | None = None,
) -> list[str]:
    """Build session options; filesystem access is granted only through `granted_dirs`."""
    args: list[str] = ["--log-level=debug", f"--log-dir={log_dir.resolve()}"] if log_dir is not None else []
    if mcp_config_json:
        args.append(f"--additional-mcp-config={mcp_config_json}")
    args.extend(f"--plugin-dir={plugin_dir}" for plugin_dir in plugin_dirs)
    args.extend(f"--add-dir={granted_dir}" for granted_dir in granted_dirs)
    if custom_agent:
        args.append(f"--agent={custom_agent}")
    return args


def invoke_copilot(
    prompt: str,
    model: str,
    work_dir: Path,
    timeout: int,
    env: Mapping[str, str],
    options: CopilotOptions | None = None,
) -> tuple[AgentMetrics | None, str]:
    """Run a Copilot session; tools and custom instructions are disabled by default."""
    options = options or CopilotOptions()
    extra_args = copilot_session_args(
        options.log_dir,
        options.mcp_config_json,
        plugin_dirs=options.plugin_dirs,
        granted_dirs=options.granted_dirs,
        custom_agent=options.custom_agent,
    )
    overrides = None if options.workspace_mcp is None else {"GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": str(options.workspace_mcp).lower()}
    process_env = agent_subprocess_env(env, overrides)
    logger.info("Executing Copilot CLI in directory: %s", work_dir)

    try:
        return invoke_cli(
            prompt=prompt,
            model=model,
            work_dir=work_dir,
            timeout=timeout,
            env=process_env,
            allow_all_tools=options.allow_all_tools,
            custom_instructions=options.custom_instructions,
            extra_args=(*extra_args, *options.extra_args),
        )
    except subprocess.TimeoutExpired as exc:
        logger.exception("Copilot CLI timed out after %s seconds", timeout)
        raise CopilotTimeoutError(timeout, stdout=exc.stdout, stderr=exc.stderr) from exc
    except subprocess.CalledProcessError as exc:
        logger.exception("Copilot CLI execution failed: %s", exc.stderr)
        raise CopilotProcessError(f"Copilot CLI execution failed (exit status {exc.returncode})", stdout=exc.stdout, stderr=exc.stderr, returncode=exc.returncode) from exc
    except OSError as exc:
        logger.exception("Could not start Copilot CLI")
        raise CopilotProcessError(f"Could not start Copilot CLI: {exc}") from exc
