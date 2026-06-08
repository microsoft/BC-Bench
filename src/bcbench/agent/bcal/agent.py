"""BCal agent for NL2AL evaluation — generates AL code from natural language via bcal CLI."""

import os
import shutil
import subprocess
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


class BcalLlmBackend(StrEnum):
    AZURE_OPENAI = "azure-openai"
    EXTERNAL_COMMAND = "external-command"


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


def _resolve_llm_backend() -> BcalLlmBackend:
    raw = os.environ.get("BCAL_LLM_BACKEND", BcalLlmBackend.AZURE_OPENAI.value)
    try:
        return BcalLlmBackend(raw)
    except ValueError as exc:
        valid = ", ".join(p.value for p in BcalLlmBackend)
        raise AgentError(f"Unknown BCAL_LLM_BACKEND='{raw}'. Expected one of: {valid}.") from exc


def _build_backend_cli_args(backend: BcalLlmBackend) -> list[str]:
    if backend is BcalLlmBackend.EXTERNAL_COMMAND:
        command = _require_env("BCAL_LLM_COMMAND")
        args = [
            "--llm-backend=external-command",
            f"--llm-command={command}",
        ]
        if model := os.environ.get("BCAL_LLM_MODEL"):
            args.append(f"--deployment={model}")
        return args

    endpoint = _require_env("AZURE_OPENAI_ENDPOINT")
    deployment = _require_env("AZURE_OPENAI_DEPLOYMENT")
    return [
        f"--endpoint={endpoint}",
        f"--deployment={deployment}",
    ]


def run_bcal_agent(
    entry: NL2ALEntry,
    repo_path: Path,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    bcal_executable = _resolve_bcal_executable()
    backend = _resolve_llm_backend()
    backend_args = _build_backend_cli_args(backend)

    logger.info(f"Running bcal CLI on: {entry.instance_id} (backend={backend.value})")

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
        *backend_args,
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


def run_bcal_prompt(prompt: str, package_cache_path: Path, export_folder: Path) -> str:
    """Run bcal once for a raw prompt and return its output as text (used by red teaming).

    BCal has two output channels and we surface both, so a safety judge sees whatever the tool actually produced:
      1. It always writes status/diagnostics to stdout (captured here).
      2. On success it writes generated *.al files into the export folder (read back here).

    assumptions:
      - Symbols are already present.
      - The hardcoded ``--page``/``--audience`` from the normal bcal flow are reused; for adversarial prompts the page is irrelevant since bcal is expected to refuse.
    """
    bcal_executable = _resolve_bcal_executable()
    backend_args = _build_backend_cli_args(_resolve_llm_backend())
    export_folder.mkdir(parents=True, exist_ok=True)

    cmd_args = [
        bcal_executable,
        f"--packagecachepath={package_cache_path}",
        *backend_args,
        f"--audience={_AUDIENCE}",
        f"--page={_PAGE}",
        f"--prompt={prompt}",
        f"--exportfolder={export_folder}",
    ]

    try:
        result = subprocess.run(
            cmd_args,
            timeout=_config.timeout.agent_execution,
            capture_output=True,
            text=True,
            check=True,
        )
        stdout = result.stdout or ""
    except subprocess.TimeoutExpired as exc:
        return f"(bcal timed out after {_config.timeout.agent_execution}s)\n{exc.stdout or ''}".strip()

    generated = "\n\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted(export_folder.rglob("*.al")))
    # Prefer the generated AL (the "real" output) but always append stdout so refusals and
    # diagnostics are visible when no file was produced.
    sections = [s for s in (generated, stdout) if s.strip()]
    return "\n\n".join(sections) if sections else "(bcal produced no output)"
