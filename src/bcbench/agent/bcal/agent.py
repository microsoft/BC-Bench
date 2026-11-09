"""BCal agent for NL2AL evaluation — generates AL code from natural language via bcal CLI."""

import json
import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import override

from bcbench_core.agent.experiment import ExperimentConfiguration
from bcbench_core.agent.harness import AgentHarness, AgentIdentity, AgentRequest, AgentResult
from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.agent.version import get_cli_version
from bcbench_core.artifacts import ALPACKAGES_DIRNAME
from bcbench_core.exceptions import AgentError, AgentTimeoutError
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError, field_validator

from bcbench.dataset import NL2ALEntry
from bcbench.types import HarnessName

logger = logging.getLogger(__name__)

_BCAL_TOOL = "bcal"


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


_SCENARIO_RESULT_ADAPTER: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])
_SCENARIO_RESULT_SCHEMA_VERSION = "1.0"


def _resolve_bcal_executable() -> str:
    resolved = shutil.which(_BCAL_TOOL)
    if not resolved:
        raise AgentError(f"'{_BCAL_TOOL}' executable not found on PATH.")
    return resolved


def get_bcal_version() -> str:
    return get_cli_version(shutil.which(_BCAL_TOOL), "BCal")


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


def _read_transcript(result_path: Path) -> dict[str, JsonValue]:
    # The whole scenario result is the transcript: execution identity, completion, failures, per-step compile status and evidence
    try:
        result: dict[str, JsonValue] = _SCENARIO_RESULT_ADAPTER.validate_json(result_path.read_bytes())
    except (OSError, ValidationError) as exc:
        raise AgentError(f"Could not read BCal scenario result {result_path}: {exc}") from exc
    if result.get("schemaVersion") != _SCENARIO_RESULT_SCHEMA_VERSION:
        raise AgentError(f"Unsupported BCal scenario result schemaVersion {result.get('schemaVersion')!r}, expected {_SCENARIO_RESULT_SCHEMA_VERSION!r}")
    return result


def _read_transcript_after_failure(result_path: Path) -> dict[str, JsonValue] | None:
    try:
        return _read_transcript(result_path)
    except AgentError:
        logger.warning("No usable BCal transcript after failure", exc_info=True)
        return None


@dataclass(frozen=True)
class BCalHarness(AgentHarness[NL2ALEntry, HarnessName]):
    """The bcal CLI, generating AL code for NL2AL entries into the prepared workspace."""

    backend_config: BCalBackendConfig
    timeout: int = 25 * 60

    @override
    def identity(self) -> AgentIdentity[HarnessName]:
        return AgentIdentity[HarnessName](harness=HarnessName.BCAL, version=get_bcal_version(), model=self.backend_config.model or "external-command")

    @override
    def run(self, request: AgentRequest[NL2ALEntry], /) -> AgentResult:
        entry, repo_path, backend_config = request.task, request.work_dir, self.backend_config
        timeout = self.timeout if request.timeout is None else request.timeout
        logger.info(f"Running bcal CLI on: {entry.instance_id}")

        # The .alpackages dir is created by the NL2AL pipeline setup step
        project_name: str = entry.project_paths[0]
        package_cache_path = repo_path / project_name / ALPACKAGES_DIRNAME
        if not package_cache_path.exists():
            raise AgentError(f"Package cache not found at: {package_cache_path}. Run the setup step first.")

        export_folder = repo_path / project_name / "src"
        logger.info(f"Export folder: {export_folder}")
        logger.debug(f"Package cache path: {package_cache_path}")
        logger.debug(f"Using prompt:\n{entry.get_task()}")

        # Evidence is only emitted in scenario mode
        with tempfile.TemporaryDirectory(prefix="bcbench-bcal-") as temp_dir:
            scenario_path = Path(temp_dir) / "scenario.json"
            result_path = Path(temp_dir) / "result.json"
            _write_scenario(scenario_path, entry.get_task())
            cmd_args: list[str] = [
                *_bcal_cli_args(entry, package_cache_path, export_folder, backend_config),
                f"--scenario={scenario_path}",
                f"--result={result_path}",
                "--include-evidence",
            ]
            logger.debug(f"bcal CLI command: {cmd_args}")

            try:
                start = time.monotonic()
                subprocess.run(cmd_args, timeout=timeout, check=True)
                execution_time = time.monotonic() - start
            except subprocess.TimeoutExpired:
                logger.exception(f"bcal CLI timed out after {timeout} seconds")
                metrics = AgentMetrics(execution_time=timeout)
                raise AgentTimeoutError("bcal CLI timed out", metrics=metrics, config=ExperimentConfiguration()) from None
            except subprocess.CalledProcessError as e:
                logger.exception("bcal CLI execution failed")
                raise AgentError(f"bcal CLI execution failed: {e}", transcript=_read_transcript_after_failure(result_path)) from None

            transcript: dict[str, JsonValue] = _read_transcript(result_path)

        logger.info(f"bcal CLI run complete for: {entry.instance_id}")
        return AgentResult(metrics=AgentMetrics(execution_time=execution_time), experiment=ExperimentConfiguration(), transcript=transcript)


def run_bcal_prompt(
    entry: NL2ALEntry,
    query: str,
    package_cache_path: Path,
    export_folder: Path,
    backend_config: BCalBackendConfig,
    timeout: int = 25 * 60,
) -> str:
    """Run bcal once for a raw prompt and return its output as text (used by red teaming).

    BCal writes generated AL to the export folder and status/output to stdout. Surface both while
    removing the echoed user prompt so the safety judge does not score the attack as target output.

    Unlike `BCalHarness` this raises on timeout/non-zero exit instead of returning the text: a
    red-team judge must never score bcal's own error output as if it were a harmless refusal.

    Assumes symbols are already present under ``package_cache_path``.
    """
    export_folder.mkdir(parents=True, exist_ok=True)
    cmd_args = _bcal_prompt_cmd_args(entry, query, package_cache_path, export_folder, backend_config)

    try:
        result = subprocess.run(
            cmd_args,
            timeout=timeout,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        stdout = result.stdout or ""
    except subprocess.TimeoutExpired as exc:
        details = "\n".join(filter(None, (_process_output(exc.stdout), _process_output(exc.stderr))))
        message = f"bcal CLI timed out after {timeout} seconds"
        if details:
            message = f"{message}\n{details}"
        metrics = AgentMetrics(execution_time=timeout)
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
