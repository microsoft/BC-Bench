"""GitHub Copilot CLI helpers."""

import logging
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from bcbench_core.agent.copilot.metrics import parse_output
from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.agent.version import get_cli_version
from bcbench_core.exceptions import AgentError

logger = logging.getLogger(__name__)

__all__ = ["copilot_session_args", "get_copilot_version", "invoke_copilot"]


def _find_copilot() -> str | None:
    # Prefer copilot.exe over copilot.bat/copilot.cmd shims on Windows: the .bat shim invokes
    # PowerShell, which re-parses arguments and corrupts prompts containing double quotes.
    return shutil.which("copilot.exe") or shutil.which("copilot.cmd") or shutil.which("copilot")


def get_copilot_version() -> str:
    return get_cli_version(_find_copilot(), "GitHub Copilot CLI")


def copilot_session_args(
    log_dir: Path,
    mcp_config_json: str | None = None,
    plugin_dirs: Sequence[Path] = (),
    granted_dirs: Sequence[Path] = (),
    custom_agent: str | None = None,
) -> list[str]:
    """Build session options; filesystem access is granted only through `granted_dirs`."""
    args = ["--log-level=debug", f"--log-dir={log_dir.resolve()}"]
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
    allow_all_tools: bool = False,
    custom_instructions: bool = False,
    extra_args: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
) -> tuple[AgentMetrics | None, str]:
    """Run one non-interactive Copilot CLI prompt.

    When ``allow_all_tools`` is false, the Copilot CLI is invoked with no tools available.

    Returns:
        A tuple containing parsed agent metrics, when available, and the final assistant response. The response is empty when none is emitted.
    """
    copilot_cmd = _find_copilot()
    if not copilot_cmd:
        raise AgentError("Copilot CLI not found in PATH. Please ensure it is installed and available.")

    tool_access_arg = "--allow-all-tools" if allow_all_tools else "--available-tools=none"
    cmd_args = [
        copilot_cmd,
        "--output-format=json",
        tool_access_arg,
        "--disable-builtin-mcps",
        *(("--no-custom-instructions",) if not custom_instructions else ()),
        f"--model={model}",
        *extra_args,
        f"--prompt={prompt.replace('\r', '').replace('\n', ' ')}",
    ]
    logger.debug("Copilot command args: %s", cmd_args)

    result = subprocess.run(
        cmd_args,
        cwd=str(work_dir),
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=True,
    )

    if result.stderr:
        sys.stderr.write(result.stderr)
        sys.stderr.flush()

    metrics, final_response = parse_output(result.stdout.splitlines(), log_transcript=True)
    return metrics, final_response or ""
