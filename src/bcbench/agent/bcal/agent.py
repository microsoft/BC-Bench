"""BCal agent for NL2AL evaluation — generates AL code from natural language via bcal CLI."""

import hashlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO, cast, override
from urllib.parse import urlsplit

from bcbench_core.agent.experiment import ExperimentConfiguration
from bcbench_core.agent.harness import AgentHarness, AgentIdentity, AgentRequest, AgentResult
from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.agent.version import get_cli_version
from bcbench_core.artifacts import ALPACKAGES_DIRNAME
from bcbench_core.exceptions import AgentError, AgentTimeoutError
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from bcbench.dataset import NL2ALEntry
from bcbench.types import BCalAgentRuntime, HarnessName

logger = logging.getLogger(__name__)

_BCAL_TOOL = "bcal"


class BCalBackendConfig(BaseModel):
    """Main orchestration and separately configured legacy/auxiliary inference."""

    model_config = ConfigDict(frozen=True)

    command: str | None = None
    model: str | None = None
    agent_runtime: BCalAgentRuntime = BCalAgentRuntime.LEGACY
    sdk_provider: Literal["openai"] | None = None
    sdk_base_url: str | None = None
    sdk_model: str | None = None
    sdk_api_key_env: str | None = None
    sdk_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] | None = None
    sdk_max_model_requests: int | None = Field(default=None, gt=0)
    sdk_timeout_seconds: int | None = Field(default=None, gt=0)
    inference_provider: str | None = None
    llm_provider: str | None = None
    llm_wire_api: Literal["chat-completions", "responses"] | None = None
    backend: Literal["external-command", "azure-openai"] = "external-command"
    endpoint: str | None = None

    @field_validator("command", "model", "sdk_provider", "sdk_base_url", "sdk_model", "sdk_api_key_env", "inference_provider", "llm_provider", "llm_wire_api", "endpoint", mode="before")
    @classmethod
    def _strip_optional_string(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    def cli_args(self) -> list[str]:
        sdk_values = (self.sdk_provider, self.sdk_base_url, self.sdk_model, self.sdk_api_key_env)
        if self.agent_runtime == BCalAgentRuntime.LEGACY and any(value is not None for value in (*sdk_values, self.sdk_reasoning_effort, self.sdk_max_model_requests, self.sdk_timeout_seconds)):
            raise AgentError("SDK provider settings require --agent-runtime=copilot-sdk.")
        if self.backend == "external-command" and not self.command:
            raise AgentError("BCAL_LLM_COMMAND is required.")
        if self.backend == "external-command" and self.endpoint:
            raise AgentError("BCAL endpoint requires --llm-backend=azure-openai.")
        if self.backend == "azure-openai":
            if self.command:
                raise AgentError("Azure OpenAI configuration cannot also use BCAL_LLM_COMMAND.")
            if not self.endpoint or not self.model:
                raise AgentError("Azure OpenAI legacy/auxiliary inference requires an explicit endpoint and model/deployment.")
            endpoint = urlsplit(self.endpoint)
            if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
                raise AgentError("Azure OpenAI endpoint must use HTTPS and contain no credentials, query, or fragment.")
        args: list[str] = []
        if self.agent_runtime == BCalAgentRuntime.COPILOT_SDK:
            if not all(sdk_values):
                raise AgentError("copilot-sdk requires explicit SDK provider, base URL, model, and API-key environment variable.")
            if not self.inference_provider:
                raise AgentError("copilot-sdk requires a non-secret --inference-provider identity for result attribution.")
            if not self.sdk_api_key_env or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.sdk_api_key_env):
                raise AgentError("SDK API-key setting must name an environment variable, not contain a key.")
            if not os.environ.get(self.sdk_api_key_env):
                raise AgentError("SDK API-key environment variable is not set.")
            url = urlsplit(self.sdk_base_url or "")
            if url.username or url.password or url.query or url.fragment or not url.hostname or url.path.rstrip("/") != "/v1":
                raise AgentError("SDK base URL must end in /v1 and contain no credentials, query, or fragment.")
            if url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("127.0.0.1", "::1", "localhost")):
                raise AgentError("SDK provider requires HTTPS, or HTTP on loopback only.")
            args.extend(
                [
                    "--agent-runtime=copilot-sdk",
                    f"--sdk-provider={self.sdk_provider}",
                    f"--sdk-base-url={self.sdk_base_url}",
                    f"--sdk-model={self.sdk_model}",
                    f"--sdk-api-key-env={self.sdk_api_key_env}",
                ]
            )
            for name, value in (
                ("sdk-reasoning-effort", self.sdk_reasoning_effort),
                ("sdk-max-model-requests", self.sdk_max_model_requests),
                ("sdk-timeout-seconds", self.sdk_timeout_seconds),
            ):
                if value is not None:
                    args.append(f"--{name}={value}")
        if self.backend == "external-command":
            args.extend(["--llm-backend=external-command", f"--llm-command={self.command}"])
        else:
            args.extend(["--llm-backend=azure-openai", f"--endpoint={self.endpoint}"])
        if self.model:
            args.append(f"--deployment={self.model}")
        return args

    def experiment(self, timeout: int, transcript: dict[str, JsonValue] | None = None) -> ExperimentConfiguration:
        main_model = self.sdk_model if self.agent_runtime == BCalAgentRuntime.COPILOT_SDK else self.model
        legacy_provider = self.llm_provider or self.backend
        legacy_wire_api = self.llm_wire_api or ("chat-completions" if self.backend == "azure-openai" else None)
        auxiliary: dict[str, JsonValue] = {
            "provider": legacy_provider,
            "backend": self.backend,
            "wireApi": legacy_wire_api,
            "model": self.model,
            "completionReviewModel": os.environ.get("BCAL_COMPLETION_REVIEW_MODEL") or None,
            "endpoint": self.endpoint,
            "commandSha256": hashlib.sha256(self.command.encode()).hexdigest() if self.command else None,
        }
        execution: dict[str, JsonValue] = {
            "schemaVersion": "1.0",
            "agentRuntime": self.agent_runtime.value,
            "main": {
                "provider": self.inference_provider or legacy_provider,
                "wireApi": "responses" if self.agent_runtime == BCalAgentRuntime.COPILOT_SDK else legacy_wire_api,
                "model": main_model,
                "reasoningEffort": self.sdk_reasoning_effort if self.agent_runtime == BCalAgentRuntime.COPILOT_SDK else None,
            },
            "auxiliary": auxiliary,
            "timeoutSeconds": timeout,
            "sdkMaxModelRequests": self.sdk_max_model_requests,
            "sdkTimeoutSeconds": self.sdk_timeout_seconds,
        }
        if transcript and isinstance(identity := transcript.get("executionIdentity"), dict):
            execution["bcalIdentity"] = identity
        if transcript and isinstance(runtime_identity := transcript.get("runtimeIdentity"), dict):
            execution["runtimeIdentity"] = runtime_identity
        return ExperimentConfiguration(execution=execution)

    def validate_deadline(self, timeout: int) -> None:
        if self.sdk_timeout_seconds is not None and self.sdk_timeout_seconds >= timeout:
            raise AgentError("SDK deadline must be shorter than the outer BCal process timeout to allow runtime cleanup.")


def _persist_diagnostics(
    destination: Path,
    result_path: Path,
    entry: NL2ALEntry,
    config: ExperimentConfiguration,
    metrics: AgentMetrics,
    terminal: str,
    export_folder: Path,
) -> None:
    if result_path.is_file() and result_path != destination / "result.json":
        shutil.copyfile(result_path, destination / "result.json")
    diagnostic_exports: list[str] = []
    if terminal != "succeeded":
        for source in tuple(export_folder.rglob("*.al")):
            if source.is_file() and not source.is_relative_to(destination) and source.resolve().is_relative_to(export_folder.resolve()):
                relative = source.relative_to(export_folder)
                target = destination / "exports" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                diagnostic_exports.append(str(relative))
    manifest = {
        "schemaVersion": "1.0",
        "instanceId": entry.instance_id,
        "taskPromptSha256": hashlib.sha256(entry.get_task().encode()).hexdigest(),
        "execution": config.execution,
        "metrics": metrics.model_dump(mode="json"),
        "terminalReason": terminal,
        "exportsAreDiagnostic": terminal != "succeeded",
        "diagnosticExports": diagnostic_exports,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


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


def _bcal_cmd_args(entry: NL2ALEntry, package_cache_path: Path, export_folder: Path, backend_config: BCalBackendConfig, *mode_args: str) -> list[str]:
    """Build the bcal argv shared by the nl2al agent run (scenario mode) and the red-team run (prompt mode).

    Only the mode arguments and the paths differ between the two, so keeping one builder stops the flag
    set from drifting when bcal's CLI changes.
    """
    return [
        _resolve_bcal_executable(),
        f"--packagecachepath={package_cache_path}",
        *backend_config.cli_args(),
        f"--audience={entry.audience}",
        f"--page={entry.page}",
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


def _result_metrics(transcript: dict[str, JsonValue] | None, execution_time: float) -> AgentMetrics:
    if transcript is None:
        return AgentMetrics(execution_time=execution_time)
    totals = transcript.get("totals")
    evidence = transcript.get("agentRuntimeEvidence")
    identity = transcript.get("runtimeIdentity")
    sdk = isinstance(identity, dict) and identity.get("agentRuntime") == "copilot-sdk"
    recorded = not sdk or (isinstance(evidence, list) and any(isinstance(turn, dict) and turn.get("combinedUsageAvailability") == "recorded-subtotal" for turn in evidence))

    def token_count(name: str) -> int | None:
        if not recorded or not isinstance(totals, dict) or (value := totals.get(name)) is None:
            return None
        if type(value) is int and value >= 0:
            return value
        logger.warning("BCal reported invalid %s; measurement remains unavailable", name)
        return None

    prompt_tokens = token_count("inputTokens")
    completion_tokens = token_count("outputTokens")
    tools = transcript.get("toolUsage")
    tool_usage: dict[str, int] | None = None
    if isinstance(tools, list):
        tool_usage = {}
        for tool in tools:
            if not isinstance(tool, dict) or not isinstance(name := tool.get("name"), str) or not name or type(started := tool.get("started")) is not int or started < 0 or name in tool_usage:
                logger.warning("BCal reported invalid aggregate tool usage; measurement remains unavailable")
                tool_usage = None
                break
            tool_usage[name] = started
    return AgentMetrics(
        execution_time=execution_time,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens if prompt_tokens is not None and completion_tokens is not None else None,
        tool_usage=tool_usage,
    )


def _require_completed(transcript: dict[str, JsonValue], *, metrics: AgentMetrics, config: ExperimentConfiguration) -> None:
    steps = transcript.get("steps")
    export = transcript.get("export")
    if (
        transcript.get("completed") is not True
        or transcript.get("failure") is not None
        or not isinstance(steps, list)
        or not steps
        or any(not isinstance(step, dict) or step.get("status") != "succeeded" or step.get("failure") is not None for step in steps)
        or (isinstance(export, dict) and export.get("success") is False)
    ):
        raise AgentError("BCal scenario did not complete successfully; exported files are diagnostics only.", transcript=transcript, metrics=metrics, config=config)
    execution = config.execution or {}
    if execution.get("agentRuntime") != "copilot-sdk":
        return
    identity = transcript.get("runtimeIdentity")
    evidence = transcript.get("agentRuntimeEvidence")
    main = execution.get("main")
    auxiliary = execution.get("auxiliary")
    if (
        not isinstance(identity, dict)
        or identity.get("contractVersion") != "1"
        or identity.get("agentRuntime") != "copilot-sdk"
        or identity.get("mainProvider") != "openai"
        or identity.get("mainProtocol") != "responses"
        or any(not isinstance(value := identity.get(name), str) or not value for name in ("sdkPackageVersion", "sdkRuntimeVersion"))
        or any(not isinstance(value := identity.get(name), str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value) for name in ("systemPromptSha256", "toolCatalogSha256"))
        or not isinstance(main, dict)
        or identity.get("mainModel") != main.get("model")
        or identity.get("reasoningEffort") != main.get("reasoningEffort")
        or not isinstance(auxiliary, dict)
        or identity.get("auxiliaryProvider") != auxiliary.get("backend")
        or identity.get("completionReviewModel") != auxiliary.get("completionReviewModel")
        or (auxiliary.get("model") is not None and identity.get("auxiliaryModel") != auxiliary.get("model"))
        or (auxiliary.get("wireApi") is not None and identity.get("auxiliaryProtocol") != auxiliary.get("wireApi"))
        or (execution.get("sdkMaxModelRequests") is not None and identity.get("maxModelRequests") != execution.get("sdkMaxModelRequests"))
        or (execution.get("sdkTimeoutSeconds") is not None and identity.get("timeoutSeconds") != execution.get("sdkTimeoutSeconds"))
        or not isinstance(export, dict)
        or export.get("attempted") is not True
        or export.get("success") is not True
        or not isinstance(evidence, list)
        or len(evidence) != sum(isinstance(step, dict) and step.get("type") == "user" for step in steps)
        or not evidence
        or any(
            not isinstance(turn, dict)
            or turn.get("contractVersion") != "1"
            or type(turn.get("turn")) is not int
            or turn.get("turn") != index
            or turn.get("terminalState") != "completed"
            or turn.get("domainCompleted") is not True
            for index, turn in enumerate(evidence, start=1)
        )
    ):
        raise AgentError(
            "BCal SDK runtime identity, terminal/domain completion or export was not verified; exported files are diagnostics only.", transcript=transcript, metrics=metrics, config=config
        )


def _run_bcal_process(args: list[str], *, timeout: int, stdout: TextIO | int = subprocess.PIPE, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    with subprocess.Popen(args, stdout=stdout, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", start_new_session=os.name != "nt", env=env) as process:
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # subprocess.run kills only its direct child, leaving the SDK native runtime alive.
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=30, check=True)
                except (OSError, subprocess.SubprocessError):
                    process.kill()
                    raise AgentError(f"Could not terminate owned BCal process tree (PID {process.pid}); runtime cleanup is unverified.") from None
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    logger.info("Owned BCal process group already exited: %s", process.pid)
            try:
                output, _ = process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                raise AgentError(f"Owned BCal process tree did not finish termination (PID {process.pid}); runtime cleanup is unverified.") from None
            raise subprocess.TimeoutExpired(args, timeout, output=output) from None
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, args, output=output)
        return subprocess.CompletedProcess(args, process.returncode, stdout=output)


@dataclass(frozen=True)
class BCalHarness(AgentHarness[NL2ALEntry, HarnessName]):
    """The bcal CLI, generating AL code for NL2AL entries into the prepared workspace."""

    backend_config: BCalBackendConfig
    timeout: int = 25 * 60

    @override
    def identity(self) -> AgentIdentity[HarnessName]:
        self.backend_config.cli_args()
        self.backend_config.validate_deadline(self.timeout)
        model = self.backend_config.sdk_model if self.backend_config.agent_runtime == BCalAgentRuntime.COPILOT_SDK else self.backend_config.model
        return AgentIdentity[HarnessName](harness=HarnessName.BCAL, version=get_bcal_version(), model=model or "external-command")

    @override
    def run(self, request: AgentRequest[NL2ALEntry], /) -> AgentResult:
        entry, repo_path, backend_config = request.task, request.work_dir, self.backend_config
        timeout = self.timeout if request.timeout is None else request.timeout
        backend_config.cli_args()
        backend_config.validate_deadline(timeout)
        diagnostics_dir = request.output_dir / f"{entry.instance_id}.bcal"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
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
            cmd_args = _bcal_cmd_args(entry, package_cache_path, export_folder, backend_config, f"--scenario={scenario_path}", f"--result={result_path}", "--include-evidence")
            logger.debug("BCal runtime: %s", backend_config.agent_runtime)

            start = time.monotonic()
            try:
                with (diagnostics_dir / "console.log").open("w", encoding="utf-8") as console:
                    _run_bcal_process(cmd_args, timeout=timeout, stdout=console)
                execution_time = time.monotonic() - start
            except subprocess.TimeoutExpired:
                logger.error("bcal CLI timed out after %s seconds", timeout)  # noqa: TRY400 - Subprocess exceptions expose command-line credentials.
                # A hard kill skips BCal's final result write; a result only exists if BCal hung after writing it
                transcript = _read_transcript_after_failure(result_path)
                metrics = _result_metrics(transcript, time.monotonic() - start)
                config = backend_config.experiment(timeout, transcript)
                _persist_diagnostics(diagnostics_dir, result_path, entry, config, metrics, "timeout", export_folder)
                raise AgentTimeoutError("bcal CLI timed out", metrics=metrics, config=config, transcript=transcript) from None
            except subprocess.CalledProcessError as e:
                logger.error("bcal CLI exited with status %s", e.returncode)  # noqa: TRY400 - Subprocess exceptions expose command-line credentials.
                transcript = _read_transcript_after_failure(result_path)
                metrics = _result_metrics(transcript, time.monotonic() - start)
                config = backend_config.experiment(timeout, transcript)
                _persist_diagnostics(diagnostics_dir, result_path, entry, config, metrics, f"exit-{e.returncode}", export_folder)
                raise AgentError(f"bcal CLI execution failed with status {e.returncode}", transcript=transcript, metrics=metrics, config=config) from None
            except AgentError as error:
                transcript = _read_transcript_after_failure(result_path)
                metrics = _result_metrics(transcript, time.monotonic() - start)
                config = backend_config.experiment(timeout, transcript)
                _persist_diagnostics(diagnostics_dir, result_path, entry, config, metrics, "cleanup-unverified", export_folder)
                raise AgentError(str(error), transcript=transcript, metrics=metrics, config=config) from error

            metrics = AgentMetrics(execution_time=execution_time)
            try:
                transcript = _read_transcript(result_path)
            except AgentError as error:
                config = backend_config.experiment(timeout)
                _persist_diagnostics(diagnostics_dir, result_path, entry, config, metrics, "invalid-result", export_folder)
                raise AgentError(str(error), metrics=metrics, config=config) from error
            config = backend_config.experiment(timeout, transcript)
            metrics = _result_metrics(transcript, execution_time)
            try:
                _require_completed(transcript, metrics=metrics, config=config)
            except AgentError:
                _persist_diagnostics(diagnostics_dir, result_path, entry, config, metrics, "incomplete", export_folder)
                raise
            _persist_diagnostics(diagnostics_dir, result_path, entry, config, metrics, "succeeded", export_folder)

        logger.info(f"bcal CLI run complete for: {entry.instance_id}")
        return AgentResult(metrics=metrics, experiment=config, transcript=transcript)


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
    diagnostics_dir = export_folder / ".bcal"
    diagnostics_dir.mkdir(exist_ok=True)
    result_path = diagnostics_dir / "result.json"
    prompt_entry = entry.model_copy(update={"nl_prompt": query})
    if backend_config.agent_runtime == BCalAgentRuntime.COPILOT_SDK:
        scenario_path = diagnostics_dir / "scenario.json"
        scenario_path.write_text(json.dumps({"schemaVersion": _SCENARIO_SCHEMA_VERSION, "steps": [{"id": "benchmark-prompt", "type": "user", "text": query}]}), encoding="utf-8")
        mode_args = (f"--scenario={scenario_path}", f"--result={result_path}", "--include-evidence")
    else:
        mode_args = (f"--prompt={query}",)
    cmd_args = _bcal_cmd_args(entry, package_cache_path, export_folder, backend_config, *mode_args)
    backend_config.validate_deadline(timeout)

    result_path.unlink(missing_ok=True)
    start = time.monotonic()
    try:
        result = _run_bcal_process(cmd_args, timeout=timeout)
        stdout = result.stdout or ""
    except subprocess.TimeoutExpired as exc:
        details = "\n".join(filter(None, (_process_output(exc.stdout), _process_output(exc.stderr))))
        message = f"bcal CLI timed out after {timeout} seconds"
        if details:
            message = f"{message}\n{details}"
        transcript = _read_transcript_after_failure(result_path) if result_path.is_file() else None
        metrics = _result_metrics(transcript, time.monotonic() - start)
        config = backend_config.experiment(timeout, transcript)
        _persist_diagnostics(diagnostics_dir, result_path, prompt_entry, config, metrics, "timeout", export_folder)
        (diagnostics_dir / "console.log").write_text(details, encoding="utf-8")
        raise AgentTimeoutError(message, metrics=metrics, config=config, transcript=transcript) from None
    except subprocess.CalledProcessError as exc:
        details = "\n".join(filter(None, (_process_output(exc.stdout), _process_output(exc.stderr))))
        message = f"bcal CLI exited with status {exc.returncode}"
        if details:
            message = f"{message}\n{details}"
        transcript = _read_transcript_after_failure(result_path) if result_path.is_file() else None
        config = backend_config.experiment(timeout, transcript)
        metrics = _result_metrics(transcript, time.monotonic() - start)
        _persist_diagnostics(diagnostics_dir, result_path, prompt_entry, config, metrics, f"exit-{exc.returncode}", export_folder)
        (diagnostics_dir / "console.log").write_text(details, encoding="utf-8")
        raise AgentError(message, config=config, metrics=metrics, transcript=transcript) from None
    except AgentError as error:
        transcript = _read_transcript_after_failure(result_path) if result_path.is_file() else None
        config = backend_config.experiment(timeout, transcript)
        metrics = _result_metrics(transcript, time.monotonic() - start)
        _persist_diagnostics(diagnostics_dir, result_path, prompt_entry, config, metrics, "cleanup-unverified", export_folder)
        raise AgentError(str(error), config=config, metrics=metrics, transcript=transcript) from error

    metrics = AgentMetrics(execution_time=time.monotonic() - start)
    config = backend_config.experiment(timeout)
    (diagnostics_dir / "console.log").write_text("\n".join(filter(None, (stdout, result.stderr))), encoding="utf-8")
    if backend_config.agent_runtime == BCalAgentRuntime.COPILOT_SDK:
        try:
            transcript = _read_transcript(result_path)
            config = backend_config.experiment(timeout, transcript)
            metrics = _result_metrics(transcript, time.monotonic() - start)
            _require_completed(transcript, metrics=metrics, config=config)
        except AgentError as error:
            _persist_diagnostics(diagnostics_dir, result_path, prompt_entry, config, metrics, "incomplete", export_folder)
            raise AgentError(str(error), metrics=metrics, config=config, transcript=error.transcript) from error
    _persist_diagnostics(diagnostics_dir, result_path, prompt_entry, config, metrics, "succeeded", export_folder)

    generated: str = "\n\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted(export_folder.rglob("*.al")))
    trimmed_stdout = _trim_prompt_echo(stdout, query)
    sections: list[str] = [section for section in (generated, trimmed_stdout) if section.strip()]
    return "\n\n".join(sections) if sections else "(bcal produced no output)"
