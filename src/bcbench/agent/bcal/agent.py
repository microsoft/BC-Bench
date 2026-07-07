"""BCal agent for NL2AL evaluation — generates AL code from natural language via bcal CLI."""

import os
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
_BCAL_EXECUTABLE_ENV = "BCAL_EXECUTABLE"


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
    """Resolve the bcal executable, preferring an explicit ``BCAL_EXECUTABLE`` override over PATH.

    Harms/XPIA injection requires a bcal build with the harm-fixture wiring; a stale global tool on
    PATH silently produces meaningless results. Set ``BCAL_EXECUTABLE`` to the local build's exe to
    pin it deterministically instead of relying on PATH ordering.
    """
    override = os.environ.get(_BCAL_EXECUTABLE_ENV, "").strip()
    if override:
        if not Path(override).is_file():
            raise AgentError(f"{_BCAL_EXECUTABLE_ENV}='{override}' does not point to an existing file.")
        return override
    resolved = shutil.which(_BCAL_TOOL)
    if not resolved:
        raise AgentError(f"'{_BCAL_TOOL}' executable not found on PATH (and {_BCAL_EXECUTABLE_ENV} is unset).")
    return resolved


def bcal_version(executable: str | None = None) -> str:
    """Return the resolved bcal ``--version`` string (best-effort; never raises)."""
    exe = executable or _resolve_bcal_executable()
    try:
        result = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30, check=False)
        return (result.stdout or result.stderr or "").strip() or "(unknown)"
    except (OSError, subprocess.SubprocessError):
        return "(unknown)"


def run_bcal_agent(
    entry: NL2ALEntry,
    repo_path: Path,
    backend_config: BCalBackendConfig,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    bcal_executable = _resolve_bcal_executable()
    backend_args = backend_config.cli_args()

    logger.info(f"Running bcal CLI on: {entry.instance_id} (backend={backend_config.backend.value})")

    # The .alpackages dir is created by the NL2AL pipeline setup step
    project_name: str = entry.project_paths[0]
    package_cache_path = repo_path / project_name / _config.file_patterns.alpackages_dirname
    if not package_cache_path.exists():
        raise AgentError(f"Package cache not found at: {package_cache_path}. Run the setup step first.")

    export_folder = repo_path / project_name / _config.file_patterns.nl2al_export_subdir

    cmd_args = [
        bcal_executable,
        f"--packagecachepath={package_cache_path}",
        *backend_args,
        f"--audience={entry.audience}",
        f"--page={entry.page}",
        f"--prompt={entry.get_task()}",
        f"--exportfolder={export_folder}",
    ]

    logger.info(f"Executing bcal CLI: {bcal_executable}")
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
    harms_fixture_path: Path | None = None,
    log_full_path: Path | None = None,
) -> str:
    """Run bcal once for a raw prompt and return its output as text (used by red teaming and harms testing).

    The response is exactly one channel so it is unambiguous to evaluate:
      - If bcal generated any AL, the response is the **full** generated AL (every ``*.al`` file it wrote,
        concatenated) and nothing else. This is the real artifact a judge should score.
      - Otherwise (a refusal, an error, or a chat-only reply) the response is bcal's stdout.

    assumptions:
      - Symbols are already present.
      - ``query`` is the (adversarial) prompt sent to bcal; ``--page``/``--audience`` come from the dataset entry and for adversarial prompts the page is irrelevant since bcal is expected to refuse.

    Args:
        harms_fixture_path: optional harms-fixture manifest injected via ``--harms-fixture`` (indirect/XPIA harms testing). When None, behavior is unchanged.
        log_full_path: optional path for bcal ``--log <path> --log-full`` JSONL, capturing full request/response payloads for post-hoc tool-call inspection.
    """
    bcal_executable = _resolve_bcal_executable()
    backend_args = backend_config.cli_args()
    export_folder.mkdir(parents=True, exist_ok=True)

    cmd_args = [
        bcal_executable,
        f"--packagecachepath={package_cache_path}",
        *backend_args,
        f"--audience={entry.audience}",
        f"--page={entry.page}",
        f"--prompt={query}",
        f"--exportfolder={export_folder}",
    ]
    if harms_fixture_path is not None:
        cmd_args.append(f"--harms-fixture={harms_fixture_path}")
    if log_full_path is not None:
        cmd_args.extend([f"--log={log_full_path}", "--log-full"])

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
        return f"(bcal timed out after {_config.timeout.bcal_execution}s)\n{exc.stdout or ''}".strip()
    except subprocess.CalledProcessError as exc:
        # Even on a non-zero exit bcal may have written AL; prefer that, else surface its own output
        # (the red-team framework would otherwise report only "Something went wrong Command [...]").
        generated = _read_generated_al(export_folder)
        if generated:
            return generated
        details = "\n".join(s.strip() for s in (exc.stdout, exc.stderr) if s and s.strip())
        return f"(bcal exited with status {exc.returncode})\n{details}".strip()

    # If any AL was generated, that full AL *is* the response; otherwise fall back to the chat/stdout.
    generated = _read_generated_al(export_folder)
    if generated:
        return generated
    if stdout.strip():
        return stdout
    return "(bcal produced no output)"


def _read_generated_al(export_folder: Path) -> str:
    """Return every generated ``*.al`` file under ``export_folder``, concatenated in full (empty if none)."""
    al_files = sorted(export_folder.rglob("*.al"))
    return "\n\n".join(p.read_text(encoding="utf-8", errors="replace") for p in al_files).strip()
