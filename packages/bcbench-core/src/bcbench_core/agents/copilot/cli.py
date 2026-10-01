import logging
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from bcbench_core.agents.copilot.metrics import parse_output
from bcbench_core.exceptions import AgentError
from bcbench_core.types import AgentMetrics

logger = logging.getLogger(__name__)


def _find_copilot() -> str | None:
    return shutil.which("copilot.exe") or shutil.which("copilot.cmd") or shutil.which("copilot")


def get_copilot_version() -> str:
    executable = _find_copilot()
    if executable is None:
        raise AgentError("GitHub Copilot CLI not found in PATH")
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise AgentError(f"Could not determine GitHub Copilot CLI version: {error}") from error
    match = re.search(r"\b\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\b", result.stdout)
    if match is None:
        raise AgentError(f"Unrecognized GitHub Copilot CLI version output: {result.stdout!r}")
    return match.group()


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
