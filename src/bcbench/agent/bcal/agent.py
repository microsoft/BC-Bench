"""BCal agent for NL2AL evaluation — generates AL code from natural language via bcal CLI."""

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from bcbench_core.artifacts import ALPACKAGES_DIRNAME
from pydantic import BaseModel, ConfigDict, field_validator

from bcbench.config import get_config
from bcbench.dataset import NL2ALEntry
from bcbench.exceptions import AgentError, AgentInfrastructureError, AgentTimeoutError
from bcbench.types import AgentMetrics, ExperimentConfiguration

logger = logging.getLogger(__name__)
_config = get_config()

_BCAL_TOOL = "bcal"
_LLM_API_ERROR_FILE_ENV = "BCBENCH_LLM_API_ERROR_FILE"
_LLM_API_ERROR_FILENAME = ".bcbench-llm-api-error.json"


class BCalBackendConfig(BaseModel):
    """Configuration for bcal's external-command LLM bridge."""

    model_config = ConfigDict(frozen=True)

    command: str | None = None
    model: str | None = None

    @field_validator("command", "model", mode="before")
    @classmethod
    def _strip_optional_string(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    def cli_args(self) -> list[str]:
        if not self.command:
            raise AgentError("BCAL_LLM_COMMAND is required.")
        args = ["--llm-backend=external-command", f"--llm-command={self.command}"]
        if self.model:
            args.append(f"--deployment={self.model}")
        return args


def _resolve_bcal_executable() -> str:
    resolved = shutil.which(_BCAL_TOOL)
    if not resolved:
        raise AgentError(f"'{_BCAL_TOOL}' executable not found on PATH.")
    return resolved


def _process_output(output: str | bytes | None) -> str:
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace").strip()
    return (output or "").strip()


def _take_llm_api_infrastructure_error(error_file: Path, metrics: AgentMetrics) -> AgentInfrastructureError | None:
    if not error_file.is_file():
        return None

    try:
        payload = json.loads(error_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise AgentError(f"Could not read BCal LLM API infrastructure error marker {error_file}: {error}") from error
    finally:
        error_file.unlink(missing_ok=True)

    if not isinstance(payload, dict):
        raise AgentError(f"Invalid BCal LLM API infrastructure error marker: {payload!r}")

    provider = payload.get("provider")
    status_code = payload.get("status_code")
    message = payload.get("message")
    if provider != "llm_api" or not isinstance(status_code, int) or not 500 <= status_code <= 599 or not isinstance(message, str):
        raise AgentError(f"Invalid BCal LLM API infrastructure error marker: {payload!r}")

    return AgentInfrastructureError(
        f"LLM API infrastructure error (HTTP {status_code}): {message}",
        provider=provider,
        status_code=status_code,
        metrics=metrics,
        config=ExperimentConfiguration(),
    )


def _raise_llm_api_infrastructure_error(error_file: Path, metrics: AgentMetrics) -> None:
    if infrastructure_error := _take_llm_api_infrastructure_error(error_file, metrics):
        raise infrastructure_error from None


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


def run_bcal_agent(
    entry: NL2ALEntry,
    repo_path: Path,
    backend_config: BCalBackendConfig,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    logger.info(f"Running bcal CLI on: {entry.instance_id}")

    # The .alpackages dir is created by the NL2AL pipeline setup step
    project_name: str = entry.project_paths[0]
    package_cache_path = repo_path / project_name / ALPACKAGES_DIRNAME
    if not package_cache_path.exists():
        raise AgentError(f"Package cache not found at: {package_cache_path}. Run the setup step first.")

    export_folder = repo_path / project_name / _config.file_patterns.nl2al_export_subdir
    cmd_args = _bcal_cmd_args(entry, entry.get_task(), package_cache_path, export_folder, backend_config)
    error_file = package_cache_path.parent / _LLM_API_ERROR_FILENAME
    error_file.unlink(missing_ok=True)
    process_env = {**os.environ, _LLM_API_ERROR_FILE_ENV: str(error_file)}

    logger.info(f"Export folder: {export_folder}")
    logger.debug(f"Package cache path: {package_cache_path}")
    logger.debug(f"Using prompt:\n{entry.get_task()}")
    logger.debug(f"bcal CLI command: {cmd_args}")

    start = time.monotonic()
    try:
        subprocess.run(
            cmd_args,
            timeout=_config.timeout.bcal_execution,
            check=True,
            env=process_env,
        )
        execution_time = time.monotonic() - start
        metrics = AgentMetrics(execution_time=execution_time)
        _raise_llm_api_infrastructure_error(error_file, metrics)

        logger.info(f"bcal CLI run complete for: {entry.instance_id}")
        return metrics, ExperimentConfiguration()
    except subprocess.TimeoutExpired:
        logger.exception(f"bcal CLI timed out after {_config.timeout.bcal_execution} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.bcal_execution)
        _raise_llm_api_infrastructure_error(error_file, metrics)
        raise AgentTimeoutError("bcal CLI timed out", metrics=metrics, config=ExperimentConfiguration()) from None
    except subprocess.CalledProcessError as e:
        metrics = AgentMetrics(execution_time=time.monotonic() - start)
        _raise_llm_api_infrastructure_error(error_file, metrics)
        logger.exception(f"bcal CLI execution failed: {e.stderr}")
        raise AgentError(f"bcal CLI execution failed: {e}") from None
    except AgentInfrastructureError:
        raise
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

    BCal writes generated AL to the export folder and status/output to stdout. Surface both while
    removing the echoed user prompt so the safety judge does not score the attack as target output.

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
    trimmed_stdout = _trim_prompt_echo(stdout, query)
    sections: list[str] = [section for section in (generated, trimmed_stdout) if section.strip()]
    return "\n\n".join(sections) if sections else "(bcal produced no output)"
