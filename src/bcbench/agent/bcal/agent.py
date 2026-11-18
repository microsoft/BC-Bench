"""BCal agent for NL2AL evaluation — generates AL code from natural language via bcal CLI."""

import json
import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast, override

from bcbench_core.agent.experiment import ExperimentConfiguration
from bcbench_core.agent.harness import AgentHarness, AgentIdentity, AgentRequest, AgentResult
from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.agent.version import get_cli_version
from bcbench_core.artifacts import ALPACKAGES_DIRNAME
from bcbench_core.exceptions import AgentError, AgentTimeoutError
from pydantic import BaseModel, ConfigDict, JsonValue, field_validator

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


# BCal versions the scenario input and the result output independently
_SCENARIO_SCHEMA_VERSION = "1.0"
# BCal builds before bic/BC-DeveloperExperience#8982 labelled the same result layout "1.1"
_RESULT_SCHEMA_VERSIONS = ("1.0", "1.1")


def _resolve_bcal_executable() -> str:
    resolved = shutil.which(_BCAL_TOOL)
    if not resolved:
        raise AgentError(f"'{_BCAL_TOOL}' executable not found on PATH.")
    return resolved


def get_bcal_version() -> str:
    return get_cli_version(shutil.which(_BCAL_TOOL), "BCal")


def _bcal_cmd_args(
    page: str,
    audience: str,
    package_cache_path: Path,
    export_folder: Path,
    backend_config: BCalBackendConfig,
    *mode_args: str,
    executable: Path | None = None,
) -> list[str]:
    return [
        str(executable) if executable is not None else _resolve_bcal_executable(),
        f"--packagecachepath={package_cache_path}",
        *backend_config.cli_args(),
        f"--audience={audience}",
        f"--page={page}",
        f"--exportfolder={export_folder}",
        *mode_args,
    ]


def _read_transcript(result_path: Path) -> dict[str, JsonValue]:
    # The whole scenario result is the transcript: execution identity, completion, failures, per-step compile status and evidence
    try:
        result = cast(JsonValue, json.loads(result_path.read_bytes()))
    except (OSError, ValueError) as exc:
        raise AgentError(f"Could not read BCal scenario result {result_path}: {exc}") from exc
    if not isinstance(result, dict) or result.get("schemaVersion") not in _RESULT_SCHEMA_VERSIONS:
        raise AgentError(f"Unsupported BCal scenario result in {result_path}, expected schemaVersion in {_RESULT_SCHEMA_VERSIONS}")
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

        # Only scenario mode writes a result file with the transcript; --scenario takes a file, not inline JSON
        with tempfile.TemporaryDirectory(prefix="bcbench-bcal-") as temp_dir:
            scenario_path = Path(temp_dir) / "scenario.json"
            result_path = Path(temp_dir) / "result.json"
            scenario = {"schemaVersion": _SCENARIO_SCHEMA_VERSION, "steps": [{"id": "benchmark-prompt", "type": "user", "text": entry.get_task()}]}
            scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
            cmd_args = _bcal_cmd_args(entry.page, entry.audience, package_cache_path, export_folder, backend_config, f"--scenario={scenario_path}", f"--result={result_path}", "--include-evidence")
            logger.debug(f"bcal CLI command: {cmd_args}")

            try:
                start = time.monotonic()
                subprocess.run(cmd_args, timeout=timeout, check=True)
                execution_time = time.monotonic() - start
            except subprocess.TimeoutExpired:
                logger.exception(f"bcal CLI timed out after {timeout} seconds")
                metrics = AgentMetrics(execution_time=timeout)
                # A hard kill skips BCal's final result write; a result only exists if BCal hung after writing it
                raise AgentTimeoutError("bcal CLI timed out", metrics=metrics, config=ExperimentConfiguration(), transcript=_read_transcript_after_failure(result_path)) from None
            except subprocess.CalledProcessError as e:
                logger.exception("bcal CLI execution failed")
                raise AgentError(f"bcal CLI execution failed: {e}", transcript=_read_transcript_after_failure(result_path)) from None

            transcript: dict[str, JsonValue] = _read_transcript(result_path)

        logger.info(f"bcal CLI run complete for: {entry.instance_id}")
        return AgentResult(metrics=AgentMetrics(execution_time=execution_time), experiment=ExperimentConfiguration(), transcript=transcript)


@dataclass(frozen=True)
class BCalPromptResult:
    exit_code: int
    timed_out: bool


def run_bcal_prompt(
    query: str,
    *,
    page: str,
    audience: str,
    package_cache_path: Path,
    export_folder: Path,
    backend_config: BCalBackendConfig,
    executable: Path,
    output: Path,
    fixture: Path | None = None,
    timeout: int = 25 * 60,
) -> BCalPromptResult:
    """Keep process output private; callers must score structured assistant evidence, never stdout."""
    export_folder.mkdir(parents=True, exist_ok=True)
    cmd_args = _bcal_cmd_args(
        page,
        audience,
        package_cache_path,
        export_folder,
        backend_config,
        f"--prompt={query}",
        f"--log={output / 'runtime.jsonl'}",
        "--log-full",
        executable=executable,
    )
    if fixture is not None:
        cmd_args.append(f"--harms-fixture={fixture}")
    (output / "command.json").write_text(json.dumps(cmd_args, ensure_ascii=False), encoding="utf-8")
    started = time.monotonic()
    timed_out = False
    with (output / "stdout.txt").open("wb") as stdout, (output / "stderr.txt").open("wb") as stderr:
        process = subprocess.Popen(cmd_args, cwd=output, stdout=stdout, stderr=stderr)
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Terminate only this Windows invocation and its bridge children.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=True, stdout=stderr, stderr=stderr)
            exit_code = process.wait()
            timed_out = True
    (output / "process.json").write_text(json.dumps({"exit_code": exit_code, "timed_out": timed_out, "duration_seconds": time.monotonic() - started}), encoding="utf-8")
    return BCalPromptResult(exit_code=exit_code, timed_out=timed_out)
