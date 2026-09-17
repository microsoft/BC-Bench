"""GitHub Copilot CLI helpers."""

import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from bcbench.agent.copilot.metrics import parse_output
from bcbench.agent.shared.contained_process import (
    AgentExecutionPolicy,
    ContainedProcessInfrastructureError,
    ContainedProcessRequest,
    run_contained_process,
    should_log_transcript,
)
from bcbench.agent.shared.version import get_cli_version
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.types import AgentMetrics

logger = get_logger(__name__)

__all__ = ["get_copilot_version", "invoke_copilot"]


def _find_copilot() -> str | None:
    # Prefer copilot.exe over copilot.bat/copilot.cmd shims on Windows: the .bat shim invokes
    # PowerShell, which re-parses arguments and corrupts prompts containing double quotes.
    return shutil.which("copilot.exe") or shutil.which("copilot.cmd") or shutil.which("copilot")


def get_copilot_version() -> str:
    return get_cli_version(_find_copilot(), "GitHub Copilot CLI")


def invoke_copilot(
    *,
    prompt: str,
    model: str,
    work_dir: Path,
    timeout: int,
    allow_all_tools: bool = False,
    custom_instructions: bool = False,
    extra_args: Sequence[str] = (),
    mcp_server_names: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
    execution_policy: AgentExecutionPolicy | None = None,
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
    logger.debug(
        "Copilot invocation: executable=%s model=%s tool_access=%s custom_instructions=%s mcp_servers=%s plugins=%d additional_dirs=%d custom_agent=%s extra_args=%d prompt_chars=%d",
        copilot_cmd,
        model,
        "all" if allow_all_tools else "none",
        custom_instructions,
        list(mcp_server_names),
        sum(arg.startswith("--plugin-dir") for arg in extra_args),
        sum(arg.startswith("--add-dir") for arg in extra_args),
        any(arg.startswith("--agent") for arg in extra_args),
        len(extra_args),
        len(prompt),
    )

    if execution_policy is not None and execution_policy.contain_process_tree:
        try:
            contained_result = run_contained_process(
                ContainedProcessRequest(
                    command=tuple(cmd_args),
                    cwd=work_dir,
                    env=dict(env) if env is not None else {},
                    timeout_seconds=timeout,
                    identity=execution_policy.restricted_identity,
                    python_executable=execution_policy.python_executable,
                    worker_path=execution_policy.worker_path,
                    worker_sha256=execution_policy.worker_sha256,
                )
            )
        except subprocess.CalledProcessError as exc:
            raise ContainedProcessInfrastructureError.from_called_process_error(exc) from exc
        result = subprocess.CompletedProcess(
            args=(copilot_cmd,),
            returncode=contained_result.returncode,
            stdout=contained_result.stdout,
            stderr=contained_result.stderr,
        )
        result.check_returncode()
    else:
        try:
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
        except subprocess.CalledProcessError as exc:
            raise subprocess.CalledProcessError(
                exc.returncode,
                (copilot_cmd,),
                output=exc.output,
                stderr=exc.stderr,
            ) from None

    if result.stderr:
        logger.debug("Copilot CLI stderr suppressed: character_count=%d", len(result.stderr))

    metrics, final_response = parse_output(
        result.stdout.splitlines(),
        log_transcript=should_log_transcript(execution_policy),
    )
    return metrics, final_response or ""
