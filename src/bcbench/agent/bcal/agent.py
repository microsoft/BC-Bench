"""BCal agent for NL2AL evaluation — generates AL code from natural language via bcal CLI."""

import json
import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from bcbench_core.artifacts import ALPACKAGES_DIRNAME
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from bcbench.config import get_config
from bcbench.dataset import NL2ALEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.types import AgentMetrics, BCalExecutionIdentity, ExperimentConfiguration

logger = logging.getLogger(__name__)
_config = get_config()

_BCAL_TOOL = "bcal"
_BCAL_COMPLETION_REVIEW_MODEL_OPTION = "--completion-review-deployment"


class BCalBackendConfig(BaseModel):
    """Configuration for bcal's external-command LLM bridge."""

    model_config = ConfigDict(frozen=True)

    command: str | None = None
    model: str | None = None
    completion_review_model: str | None = None

    @field_validator("command", "model", "completion_review_model", mode="before")
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

    def completion_review_cli_args(self) -> list[str]:
        if not self.completion_review_model:
            return []
        return [_BCAL_COMPLETION_REVIEW_MODEL_OPTION, self.completion_review_model]


class _BCalScenarioStepResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    type: Literal["user"]
    status: Literal["succeeded", "failed"]
    failure: "_BCalFailure | None" = None


class _BCalFailure(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str
    message: str
    step_id: str | None = Field(default=None, alias="stepId")
    retryable: bool | None = None


class _BCalOutputStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    attempted: bool
    success: bool
    path: str | None = None
    file_name: str | None = Field(default=None, alias="fileName")
    files_exported: int | None = Field(default=None, alias="filesExported")
    entries_exported: int | None = Field(default=None, alias="entriesExported")
    message: str | None = None


class _BCalScenarioResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    execution_identity: BCalExecutionIdentity = Field(alias="executionIdentity")
    evidence: dict[str, Any] | None = None
    completed: bool
    steps: list[_BCalScenarioStepResult] = Field(min_length=1)
    export: _BCalOutputStatus | None = None
    session_archive: _BCalOutputStatus | None = Field(default=None, alias="sessionArchive")
    failure: _BCalFailure | None = None


class BCalScenarioError(AgentError):
    def __init__(self, message: str, scenario_result: _BCalScenarioResult | None = None) -> None:
        self.scenario_result = scenario_result
        super().__init__(message)


@dataclass(frozen=True)
class BCalRunResult:
    metrics: AgentMetrics
    experiment: ExperimentConfiguration
    execution_identity: BCalExecutionIdentity
    evidence: dict[str, Any] | None


def _resolve_bcal_executable() -> str:
    resolved = shutil.which(_BCAL_TOOL)
    if not resolved:
        raise AgentError(f"'{_BCAL_TOOL}' executable not found on PATH.")
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


def _bcal_cli_args(entry: NL2ALEntry, package_cache_path: Path, export_folder: Path, backend_config: BCalBackendConfig) -> list[str]:
    return [
        _resolve_bcal_executable(),
        f"--packagecachepath={package_cache_path}",
        *backend_config.cli_args(),
        *backend_config.completion_review_cli_args(),
        f"--audience={entry.audience}",
        f"--page={entry.page}",
        f"--exportfolder={export_folder}",
    ]


def _bcal_prompt_cmd_args(entry: NL2ALEntry, prompt: str, package_cache_path: Path, export_folder: Path, backend_config: BCalBackendConfig) -> list[str]:
    return [
        *_bcal_cli_args(entry, package_cache_path, export_folder, backend_config),
        f"--prompt={prompt}",
    ]


def _write_scenario(path: Path, prompt: str) -> None:
    scenario = {
        "schemaVersion": "1.0",
        "steps": [
            {
                "id": "benchmark-prompt",
                "type": "user",
                "text": prompt,
            }
        ],
    }
    path.write_text(f"{json.dumps(scenario, indent=2)}\n", encoding="utf-8")


def _parse_scenario_result(path: Path) -> _BCalScenarioResult:
    if not path.exists():
        raise AgentError(f"BCal did not create the scenario result file: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AgentError(f"BCal scenario result is not valid UTF-8 JSON: {path}: {exc}") from exc

    try:
        result = _BCalScenarioResult.model_validate(payload)
    except ValidationError as exc:
        raise AgentError(f"BCal scenario result is incompatible with contract 1.0: {exc}") from exc

    matching_steps = [step for step in result.steps if step.id == "benchmark-prompt"]
    if len(matching_steps) != 1:
        raise AgentError("BCal scenario result must contain exactly one 'benchmark-prompt' step")
    return result


def _format_failure(failure: _BCalFailure | None) -> str:
    if failure is None:
        return "none"
    details = [f"code={failure.code}", f"message={failure.message}"]
    if failure.step_id:
        details.append(f"stepId={failure.step_id}")
    if failure.retryable is not None:
        details.append(f"retryable={str(failure.retryable).lower()}")
    return ", ".join(details)


def _format_output_status(status: _BCalOutputStatus | None) -> str:
    if status is None:
        return "not reported"
    details = [f"attempted={str(status.attempted).lower()}", f"success={str(status.success).lower()}"]
    if status.path:
        details.append(f"path={status.path}")
    if status.file_name:
        details.append(f"fileName={status.file_name}")
    if status.files_exported is not None:
        details.append(f"filesExported={status.files_exported}")
    if status.entries_exported is not None:
        details.append(f"entriesExported={status.entries_exported}")
    if status.message:
        details.append(f"message={status.message}")
    return ", ".join(details)


def _scenario_failure_message(
    exc: subprocess.CalledProcessError,
    result_path: Path,
) -> tuple[str, _BCalScenarioResult | None]:
    sections = [f"BCal scenario exited with status {exc.returncode}"]
    scenario_result: _BCalScenarioResult | None = None

    if result_path.exists():
        try:
            scenario_result = _parse_scenario_result(result_path)
        except AgentError as parse_error:
            sections.append(f"Scenario result: {parse_error}")
        else:
            benchmark_steps = [step for step in scenario_result.steps if step.id == "benchmark-prompt"]
            step_failure = benchmark_steps[0].failure if benchmark_steps else None
            sections.extend(
                [
                    f"Completed: {str(scenario_result.completed).lower()}",
                    f"Failure: {_format_failure(scenario_result.failure)}",
                    f"Step failure: {_format_failure(step_failure)}",
                    f"Export: {_format_output_status(scenario_result.export)}",
                    f"Session archive: {_format_output_status(scenario_result.session_archive)}",
                ]
            )
    else:
        sections.append(f"Scenario result: not created at {result_path}")

    stdout = _process_output(exc.stdout)
    stderr = _process_output(exc.stderr)
    if stdout:
        sections.append(f"stdout:\n{stdout}")
    if stderr:
        sections.append(f"stderr:\n{stderr}")
    return "\n".join(sections), scenario_result


def run_bcal_agent(
    entry: NL2ALEntry,
    repo_path: Path,
    backend_config: BCalBackendConfig,
) -> BCalRunResult:
    logger.info(f"Running bcal CLI on: {entry.instance_id}")

    # The .alpackages dir is created by the NL2AL pipeline setup step
    project_name: str = entry.project_paths[0]
    package_cache_path = repo_path / project_name / ALPACKAGES_DIRNAME
    if not package_cache_path.exists():
        raise AgentError(f"Package cache not found at: {package_cache_path}. Run the setup step first.")

    export_folder = repo_path / project_name / _config.file_patterns.nl2al_export_subdir

    logger.info(f"Export folder: {export_folder}")
    logger.debug(f"Package cache path: {package_cache_path}")
    logger.debug(f"Using prompt:\n{entry.get_task()}")

    try:
        with tempfile.TemporaryDirectory(prefix="bcbench-bcal-") as temp_dir:
            scenario_path = Path(temp_dir) / "scenario.json"
            result_path = Path(temp_dir) / "result.json"
            _write_scenario(scenario_path, entry.get_task())
            cmd_args = [
                *_bcal_cli_args(entry, package_cache_path, export_folder, backend_config),
                f"--scenario={scenario_path}",
                f"--result={result_path}",
                "--include-evidence",
            ]
            logger.debug(f"bcal CLI command: {cmd_args}")

            start = time.monotonic()
            try:
                subprocess.run(
                    cmd_args,
                    timeout=_config.timeout.bcal_execution,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=True,
                )
            except subprocess.CalledProcessError as exc:
                message, scenario_result = _scenario_failure_message(exc, result_path)
                logger.exception(message)
                raise BCalScenarioError(message, scenario_result=scenario_result) from None
            scenario_result = _parse_scenario_result(result_path)
        execution_time = time.monotonic() - start

        logger.info(f"bcal CLI run complete for: {entry.instance_id}")
        return BCalRunResult(
            metrics=AgentMetrics(execution_time=execution_time),
            experiment=ExperimentConfiguration(),
            execution_identity=scenario_result.execution_identity,
            evidence=scenario_result.evidence,
        )
    except subprocess.TimeoutExpired:
        logger.exception(f"bcal CLI timed out after {_config.timeout.bcal_execution} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.bcal_execution)
        raise AgentTimeoutError("bcal CLI timed out", metrics=metrics, config=ExperimentConfiguration()) from None
    except AgentError:
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
    cmd_args = _bcal_prompt_cmd_args(entry, query, package_cache_path, export_folder, backend_config)

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
