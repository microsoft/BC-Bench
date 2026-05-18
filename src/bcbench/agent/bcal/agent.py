"""bc-al agent for NL2AL evaluation — generates AL code from natural language via bcal CLI."""

import os
import shutil
import subprocess
import time
from pathlib import Path

from bcbench.config import get_config
from bcbench.dataset import NL2ALEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.types import AgentMetrics, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()

_AUDIENCE = "both"
_PAGE = "Customer Card"
_BCAL_TOOL = "bcal"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise AgentError(f"Environment variable {name} is required but not set. Add it to your .env file.")
    return value


def _resolve_bcal_executable() -> str:
    resolved = shutil.which(_BCAL_TOOL)
    if not resolved:
        raise AgentError(f"'{_BCAL_TOOL}' executable not found on PATH.")
    return resolved


def run_bcal_agent(
    entry: NL2ALEntry,
    output_dir: Path,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    azure_endpoint = _require_env("AZURE_OPENAI_ENDPOINT")
    azure_deployment = _require_env("AZURE_OPENAI_DEPLOYMENT")
    bcal_executable = _resolve_bcal_executable()

    logger.info(f"Running bcal CLI on: {entry.instance_id}")

    prompt = entry.nl_prompt

    # The .alpackages dir is created by the NL2AL pipeline setup step
    project_name = entry.project_paths[0] if entry.project_paths else "App"
    package_cache_path = output_dir / project_name / ".alpackages"
    if not package_cache_path.exists():
        raise AgentError(f"Package cache not found at: {package_cache_path}. Run the setup step first.")

    # Export folder for generated AL files
    export_folder = output_dir / project_name / "src"
    export_folder.mkdir(parents=True, exist_ok=True)

    cmd_args = [
        bcal_executable,
        "--packagecachepath",
        str(package_cache_path),
        "--endpoint",
        azure_endpoint,
        "--deployment",
        azure_deployment,
        "--audience",
        _AUDIENCE,
        "--page",
        _PAGE,
        "--prompt",
        prompt,
        "--exportfolder",
        str(export_folder),
    ]

    logger.info(f"Executing bcal CLI: {bcal_executable}")
    logger.info(f"Package cache path: {package_cache_path}")
    logger.info(f"Export folder: {export_folder}")
    logger.debug(f"Using prompt:\n{prompt}")
    logger.debug(f"bcal CLI command: {cmd_args}")

    try:
        start = time.monotonic()
        subprocess.run(
            cmd_args,
            timeout=_config.timeout.agent_execution,
            check=True,
        )
        execution_time = time.monotonic() - start

        logger.info(f"bcal CLI run complete for: {entry.instance_id}")
        return AgentMetrics(execution_time=execution_time), ExperimentConfiguration()
    except subprocess.TimeoutExpired:
        logger.exception(f"bcal CLI timed out after {_config.timeout.agent_execution} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.agent_execution)
        raise AgentTimeoutError("bcal CLI timed out", metrics=metrics, config=ExperimentConfiguration()) from None
    except subprocess.CalledProcessError as e:
        logger.exception(f"bcal CLI execution failed: {e.stderr}")
        raise AgentError(f"bcal CLI execution failed: {e}") from None
    except Exception:
        logger.exception("Unexpected error running bcal CLI")
        raise
