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


def _process_output(output: str | bytes | None) -> str:
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace").strip()
    return (output or "").strip()


def _trim_prompt_echo(stdout: str, query: str) -> str:
    compact_query = "".join(query.split())
    if not compact_query:
        return stdout.strip()

    compact_stdout_chars: list[str] = []
    stdout_positions: list[int] = []
    for position, character in enumerate(stdout):
        if not character.isspace():
            compact_stdout_chars.append(character)
            stdout_positions.append(position)

    compact_stdout = "".join(compact_stdout_chars)
    seed_length = min(24, len(compact_query))
    compact_start = compact_stdout.find(compact_query[:seed_length])
    if compact_start < 0:
        return stdout.strip()

    matched_length = seed_length
    while matched_length < len(compact_query) and compact_start + matched_length < len(compact_stdout):
        if compact_query[matched_length] != compact_stdout[compact_start + matched_length]:
            break
        matched_length += 1

    compact_end = compact_start + matched_length
    if matched_length < len(compact_query):
        if not compact_stdout.startswith("...", compact_end):
            return stdout.strip()
        compact_end += 3

    start = stdout_positions[compact_start]
    if stdout[:start].strip() not in ("", ">"):
        return stdout.strip()

    end = stdout_positions[compact_end - 1] + 1
    if stdout[max(0, start - 2) : start] == "> ":
        start -= 2
    return f"{stdout[:start]}{stdout[end:]}".strip()


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
    harms_fixture_path: Path | None = None,
    log_full_path: Path | None = None,
) -> str:
    """Run bcal once for a raw prompt and return its output as text (used by red teaming).

    BCal writes generated AL to the export folder and status/output to stdout. Surface both while
    removing the echoed user prompt so the safety judge does not score the attack as target output.

    Unlike `run_bcal_agent` this raises on timeout/non-zero exit instead of returning the text: a
    red-team judge must never score bcal's own error output as if it were a harmless refusal.

    Assumes symbols are already present under ``package_cache_path``.

    Args:
        harms_fixture_path: Optional manifest for indirect harms testing.
        log_full_path: Optional path for full bcal JSONL logs.
    """
    export_folder.mkdir(parents=True, exist_ok=True)
    cmd_args = _bcal_cmd_args(entry, query, package_cache_path, export_folder, backend_config)
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
    trimmed_stdout = _trim_prompt_echo(stdout, query)
    sections: list[str] = [section for section in (generated, trimmed_stdout) if section.strip()]
    return "\n\n".join(sections) if sections else "(bcal produced no output)"
