"""GitHub Copilot CLI helpers."""

import logging
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from bcbench_core.agent.copilot.metrics import parse_output
from bcbench_core.agent.copilot.types import CopilotOptions, CopilotProcessError
from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.agent.version import get_cli_version

logger = logging.getLogger(__name__)

__all__ = ["get_copilot_version", "run_copilot_cli"]


def _find_copilot() -> str | None:
    # Prefer copilot.exe over copilot.bat/copilot.cmd shims on Windows: the .bat shim invokes
    # PowerShell, which re-parses arguments and corrupts prompts containing double quotes.
    return shutil.which("copilot.exe") or shutil.which("copilot.cmd") or shutil.which("copilot")


def get_copilot_version() -> str:
    return get_cli_version(_find_copilot(), "GitHub Copilot CLI")


def run_copilot_cli(
    *,
    prompt: str,
    model: str,
    work_dir: Path,
    timeout: int,
    env: Mapping[str, str],
    options: CopilotOptions,
) -> tuple[AgentMetrics | None, str]:
    """Run one non-interactive Copilot CLI prompt.

    When ``options.allow_all_tools`` is false, the Copilot CLI is invoked with no tools available.
    Filesystem access is granted only through ``options.granted_dirs``.

    Returns:
        A tuple containing parsed agent metrics, when available, and the final assistant response. The response is empty when none is emitted.
    """
    copilot_cmd = _find_copilot()
    if not copilot_cmd:
        raise CopilotProcessError("Copilot CLI not found in PATH. Please ensure it is installed and available.")

    tool_access_arg = "--allow-all-tools" if options.allow_all_tools else "--available-tools=none"
    log_args = ("--log-level=debug", f"--log-dir={options.log_dir.resolve()}") if options.log_dir is not None else ()
    cmd_args = [
        copilot_cmd,
        "--output-format=json",
        tool_access_arg,
        "--disable-builtin-mcps",
        *(("--no-custom-instructions",) if not options.custom_instructions else ()),
        f"--model={model}",
        *log_args,
        *((f"--additional-mcp-config={options.mcp_config_json}",) if options.mcp_config_json else ()),
        *(f"--plugin-dir={plugin_dir}" for plugin_dir in options.plugin_dirs),
        *(f"--add-dir={granted_dir}" for granted_dir in options.granted_dirs),
        *((f"--agent={options.custom_agent}",) if options.custom_agent else ()),
        *options.extra_args,
        f"--prompt={prompt.replace('\r', '').replace('\n', ' ')}",
    ]
    logger.debug("Copilot command args: %s", cmd_args)

    result = subprocess.run(
        cmd_args,
        cwd=str(work_dir),
        env=dict(env),
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
