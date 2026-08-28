"""GitHub Copilot CLI helpers."""

import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from bcbench.agent.copilot.metrics import parse_output
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.types import AgentMetrics

logger = get_logger(__name__)

__all__ = ["invoke_copilot"]


def _find_copilot() -> str | None:
    # Prefer copilot.exe over copilot.bat/copilot.cmd shims on Windows: the .bat shim invokes
    # PowerShell, which re-parses arguments and corrupts prompts containing double quotes.
    return shutil.which("copilot.exe") or shutil.which("copilot.cmd") or shutil.which("copilot")


def invoke_copilot(
    *,
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

    metrics, final_response = parse_output(result.stdout.splitlines())
    return metrics, final_response or ""
