"""BCal agent for NL2AL evaluation — generates AL code from natural language via bcal CLI."""

import os
import shlex
import shutil
import subprocess
import sys
import time
from enum import StrEnum
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
_BC_EVAL_CAPI_BRIDGE_MODULE = "bcbench.agent.bcal.bc_eval_capi_bridge"


class BcalAIProvider(StrEnum):
    AZURE_OPENAI = "azure-openai"
    CAPI = "capi"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value or not value.strip():
        raise AgentError(f"Environment variable {name} is required but not set. Add it to your .env file.")
    return value


def _resolve_bcal_executable() -> str:
    resolved = shutil.which(_BCAL_TOOL)
    if not resolved:
        raise AgentError(f"'{_BCAL_TOOL}' executable not found on PATH.")
    return resolved


def _resolve_provider() -> BcalAIProvider:
    raw = os.environ.get("BCAL_AI_PROVIDER", BcalAIProvider.AZURE_OPENAI.value)
    try:
        return BcalAIProvider(raw)
    except ValueError as exc:
        valid = ", ".join(p.value for p in BcalAIProvider)
        raise AgentError(f"Unknown BCAL_AI_PROVIDER='{raw}'. Expected one of: {valid}.") from exc


def _resolve_deployment(provider: BcalAIProvider) -> str:
    if provider is BcalAIProvider.CAPI:
        model = os.environ.get("BCAL_AI_MODEL") or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        if not model:
            raise AgentError("BCAL_AI_MODEL or AZURE_OPENAI_DEPLOYMENT must be set when BCAL_AI_PROVIDER=capi.")
        return model
    return _require_env("AZURE_OPENAI_DEPLOYMENT")


def _default_bc_eval_capi_command() -> str:
    command = [sys.executable, "-m", _BC_EVAL_CAPI_BRIDGE_MODULE]
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return shlex.join(command)

def _resolve_capi_ai_command() -> str:
    return os.environ.get("BCAL_AI_COMMAND") or _default_bc_eval_capi_command()
    return os.environ.get("BCAL_AI_COMMAND") or _default_bc_eval_capi_command()


def _build_provider_cli_args(provider: BcalAIProvider, deployment: str) -> list[str]:
    if provider is BcalAIProvider.CAPI:
        return [
            f"--deployment={deployment}",
            "--ai-provider=external-command",
            f"--ai-command={_resolve_capi_ai_command()}",
        ]

    endpoint = _require_env("AZURE_OPENAI_ENDPOINT")
    return [
        f"--endpoint={endpoint}",
        f"--deployment={deployment}",
    ]


def run_bcal_agent(
    entry: NL2ALEntry,
    repo_path: Path,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    bcal_executable = _resolve_bcal_executable()
    provider = _resolve_provider()
    deployment = _resolve_deployment(provider)
    provider_args = _build_provider_cli_args(provider, deployment)

    logger.info(f"Running bcal CLI on: {entry.instance_id} (provider={provider.value}, deployment={deployment})")

    prompt = entry.nl_prompt

    # The .alpackages dir is created by the NL2AL pipeline setup step
    project_name = entry.project_paths[0] if entry.project_paths else "App"
    package_cache_path = repo_path / project_name / ".alpackages"
    if not package_cache_path.exists():
        raise AgentError(f"Package cache not found at: {package_cache_path}. Run the setup step first.")

    # Export folder for generated AL files
    export_folder = repo_path / project_name / "src"
    export_folder.mkdir(parents=True, exist_ok=True)

    cmd_args = [
        bcal_executable,
        f"--packagecachepath={package_cache_path}",
        *provider_args,
        f"--audience={_AUDIENCE}",
        f"--page={_PAGE}",
        f"--prompt={prompt}",
        f"--exportfolder={export_folder}",
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
