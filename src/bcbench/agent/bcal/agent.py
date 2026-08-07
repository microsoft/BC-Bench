"""BCal agent for NL2AL evaluation — generates AL code from natural language via bcal CLI."""

import shutil
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from bcbench.config import get_config
from bcbench.dataset import NL2ALEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.types import AgentMetrics, BCalLLMBackend, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()

_BCAL_TOOL = "bcal"


class BCalBackendConfig(BaseModel):
    """A resolved bcal backend plus the inputs it needs to run.

    Bundles the backend selector with its (command-entry supplied) values so call sites pass a
    single object, and the conditional "which inputs are required" rules stay in one place.
    """

    model_config = ConfigDict(frozen=True)

    backend: BCalLLMBackend
    endpoint: str | None = None
    deployment: str | None = None
    command: str | None = None
    model: str | None = None

    @field_validator("endpoint", "deployment", "command", "model", mode="before")
    @classmethod
    def _strip_optional_string(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    def cli_args(self) -> list[str]:
        match self.backend:
            case BCalLLMBackend.EXTERNAL_COMMAND:
                if not self.command:
                    raise AgentError("BCAL_LLM_COMMAND is required for the external-command backend.")
                args = ["--llm-backend=external-command", f"--llm-command={self.command}"]
                if self.model:
                    args.append(f"--deployment={self.model}")
                return args
            case BCalLLMBackend.AZURE_OPENAI:
                if not self.endpoint:
                    raise AgentError("AZURE_OPENAI_ENDPOINT is required for the azure-openai backend.")
                if not self.deployment:
                    raise AgentError("AZURE_OPENAI_DEPLOYMENT is required for the azure-openai backend.")
                return [f"--endpoint={self.endpoint}", f"--deployment={self.deployment}"]

        raise ValueError(f"Unknown BCalLLMBackend: {self.backend}")

    def model_label(self) -> str:
        match self.backend:
            case BCalLLMBackend.EXTERNAL_COMMAND:
                return self.model or self.backend.value
            case BCalLLMBackend.AZURE_OPENAI:
                return self.deployment or self.backend.value

        raise ValueError(f"Unknown BCalLLMBackend: {self.backend}")


def _resolve_bcal_executable() -> str:
    resolved = shutil.which(_BCAL_TOOL)
    if not resolved:
        raise AgentError(f"'{_BCAL_TOOL}' executable not found on PATH.")
    return resolved


def _process_output(output: str | bytes | None) -> str:
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace").strip()
    return (output or "").strip()


def _bcal_cmd_args(entry: NL2ALEntry, prompt: str, package_cache_path: Path, export_folder: Path, backend_config: BCalBackendConfig) -> list[str]:
    """Build the bcal argv shared by the nl2al agent run and the red-team single-prompt run.

    Only the prompt and the paths differ between the two, so keeping one builder stops the flag
    set from drifting when bcal's CLI changes.
    """
    return [
        _resolve_bcal_executable(),
        f"--packagecachepath={package_cache_path}",
        *backend_config.cli_args(),
        f"--audience={entry.audience}",
        f"--page={entry.page}",
        f"--prompt={prompt}",
        f"--exportfolder={export_folder}",
    ]


def run_bcal_agent(
    entry: NL2ALEntry,
    repo_path: Path,
    backend_config: BCalBackendConfig,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    logger.info(f"Running bcal CLI on: {entry.instance_id} (backend={backend_config.backend.value})")

    # The .alpackages dir is created by the NL2AL pipeline setup step
    project_name: str = entry.project_paths[0]
    package_cache_path = repo_path / project_name / _config.file_patterns.alpackages_dirname
    if not package_cache_path.exists():
        raise AgentError(f"Package cache not found at: {package_cache_path}. Run the setup step first.")

    export_folder = repo_path / project_name / _config.file_patterns.nl2al_export_subdir
    cmd_args = _bcal_cmd_args(entry, entry.get_task(), package_cache_path, export_folder, backend_config)

    logger.info(f"Export folder: {export_folder}")
    logger.debug(f"Package cache path: {package_cache_path}")
    logger.debug(f"Using prompt:\n{entry.get_task()}")
    logger.debug(f"bcal CLI command: {cmd_args}")

    try:
        start = time.monotonic()
        subprocess.run(
            cmd_args,
            timeout=_config.timeout.bcal_execution,
            check=True,
        )
        execution_time = time.monotonic() - start

        logger.info(f"bcal CLI run complete for: {entry.instance_id}")
        return AgentMetrics(execution_time=execution_time), ExperimentConfiguration()
    except subprocess.TimeoutExpired:
        logger.exception(f"bcal CLI timed out after {_config.timeout.bcal_execution} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.bcal_execution)
        raise AgentTimeoutError("bcal CLI timed out", metrics=metrics, config=ExperimentConfiguration()) from None
    except subprocess.CalledProcessError as e:
        logger.exception(f"bcal CLI execution failed: {e.stderr}")
        raise AgentError(f"bcal CLI execution failed: {e}") from None
    except Exception:
        logger.exception("Unexpected error running bcal CLI")
        raise


def run_bcal_prompt(
    entry: NL2ALEntry,
    query: str,
    package_cache_path: Path,
    export_folder: Path,
    backend_config: BCalBackendConfig,
) -> str:
    """Run bcal once for a raw prompt and return its output as text (used by red teaming).

    BCal has two output channels and we surface both, so a safety judge sees whatever the tool actually produced:
      1. It always writes status/diagnostics to stdout (captured here).
      2. On success it writes generated *.al files into the export folder (read back here).

    Unlike `run_bcal_agent` this raises on timeout/non-zero exit instead of returning the text: a
    red-team judge must never score bcal's own error output as if it were a harmless refusal.

    Assumes symbols are already present under ``package_cache_path``.
    """
    export_folder.mkdir(parents=True, exist_ok=True)
    cmd_args = _bcal_cmd_args(entry, query, package_cache_path, export_folder, backend_config)

    try:
        result = subprocess.run(
            cmd_args,
            timeout=_config.timeout.bcal_execution,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        stdout = result.stdout or ""
    except subprocess.TimeoutExpired as exc:
        details = "\n".join(filter(None, (_process_output(exc.stdout), _process_output(exc.stderr))))
        message = f"bcal CLI timed out after {_config.timeout.bcal_execution} seconds"
        if details:
            message = f"{message}\n{details}"
        metrics = AgentMetrics(execution_time=_config.timeout.bcal_execution)
        raise AgentTimeoutError(message, metrics=metrics, config=ExperimentConfiguration()) from None
    except subprocess.CalledProcessError as exc:
        details = "\n".join(filter(None, (_process_output(exc.stdout), _process_output(exc.stderr))))
        message = f"bcal CLI exited with status {exc.returncode}"
        if details:
            message = f"{message}\n{details}"
        raise AgentError(message) from None

    generated: str = "\n\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted(export_folder.rglob("*.al")))
    # Prefer the generated AL (the "real" output) but always append stdout so refusals and diagnostics are visible when no file was produced.
    sections: list[str] = [s for s in (generated, stdout) if s.strip()]
    return "\n\n".join(sections) if sections else "(bcal produced no output)"
