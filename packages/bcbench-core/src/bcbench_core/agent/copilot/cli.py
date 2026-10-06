"""GitHub Copilot CLI helpers."""

import logging
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from bcbench_core.agent.copilot.metrics import parse_output
from bcbench_core.agent.copilot.types import CopilotOptions, CopilotProcessError, CopilotTimeoutError
from bcbench_core.agent.env import agent_subprocess_env
from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.agent.version import get_cli_version

logger = logging.getLogger(__name__)

__all__ = ["copilot_session_args", "get_copilot_version", "invoke_copilot"]


def _find_copilot() -> str | None:
    # Prefer copilot.exe over copilot.bat/copilot.cmd shims on Windows: the .bat shim invokes
    # PowerShell, which re-parses arguments and corrupts prompts containing double quotes.
    return shutil.which("copilot.exe") or shutil.which("copilot.cmd") or shutil.which("copilot")


def get_copilot_version() -> str:
    return get_cli_version(_find_copilot(), "GitHub Copilot CLI")


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
    """Run one non-interactive Copilot CLI prompt.

    Tools and custom instructions are disabled unless enabled in `options`.

    Returns:
        A tuple containing parsed agent metrics, when available, and the final assistant response. The response is empty when none is emitted.
    """
    options = options or CopilotOptions()
    copilot_cmd = _find_copilot()
    if not copilot_cmd:
        raise CopilotProcessError("Copilot CLI not found in PATH. Please ensure it is installed and available.")

    extra_args = copilot_session_args(
        options.log_dir,
        options.mcp_config_json,
        plugin_dirs=options.plugin_dirs,
        granted_dirs=options.granted_dirs,
        custom_agent=options.custom_agent,
    )
    overrides = None if options.workspace_mcp is None else {"GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": str(options.workspace_mcp).lower()}
    process_env = agent_subprocess_env(env, overrides)
    tool_access_arg = "--allow-all-tools" if options.allow_all_tools else "--available-tools=none"
    cmd_args = [
        copilot_cmd,
        "--output-format=json",
        tool_access_arg,
        "--disable-builtin-mcps",
        *(("--no-custom-instructions",) if not options.custom_instructions else ()),
        f"--model={model}",
        *extra_args,
        *options.extra_args,
        f"--prompt={prompt.replace('\r', '').replace('\n', ' ')}",
    ]
    logger.info("Executing Copilot CLI in directory: %s", work_dir)
    logger.debug("Copilot command args: %s", cmd_args)

    try:
        result = subprocess.run(
            cmd_args,
            cwd=str(work_dir),
            env=process_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=True,
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

    if result.stderr:
        sys.stderr.write(result.stderr)
        sys.stderr.flush()

    metrics, final_response = parse_output(result.stdout.splitlines(), log_transcript=True)
    return metrics, final_response or ""
