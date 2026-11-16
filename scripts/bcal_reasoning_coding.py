"""Opt-in packaged BCAL coding runs; frozen studies and defaults are unchanged."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from bcal_reasoning_compatibility import CLIENT_SHA, MODELS, PACKAGE_SHA, effort, load_module, safe_response, verify_package, write_json
from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    import httpx2 as httpx
    from openai import OpenAI

    from bcbench.agent.bcal.agent import BCalBackendConfig

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SOURCE = "52f3f7f5dd2d26c83f2778d28ace9d47364b481b"
SCORER_SHA = "c563e569520b202e725d46ac58497868fefd8d48662fb8a305c9a397e14c398d"
TERMINAL_STATES = frozenset(
    ("not-started", "running", "completed", "error", "aborted", "deadline-exceeded", "input-required", "protocol-error", "incomplete", "budget-exceeded", "model-options-mismatch")
)
FAILURE_CODES = frozenset(("turn_failed", "sdk_deadline_exceeded", "scenario_canceled"))
FAILURE_SIGNATURES = {
    "Provider/runtime violated single-call planning dispatch.": "planning_dispatch_guard",
    "Dependent native tool-call order is not guaranteed for a multi-call response.": "planning_dispatch_callback",
    "Provider/runtime violated single-call BCAL dispatch.": "bcal_dispatch_guard",
    "Dependent tool-call order is not guaranteed for a multi-call response.": "bcal_dispatch_callback",
    "SDK callback arrived after the fence or overlapped workspace access.": "callback_fence_guard",
    "BCAL callback admission closed or occupied.": "callback_admission",
    "Copilot SDK did not confirm delivery of successful BCAL tool results.": "pending_delivery_at_idle",
    "SDK reported an aborted turn.": "aborted_idle",
    "SDK became idle without domain-valid completion.": "no_domain_completion_at_idle",
    "Native planning tool arguments were absent.": "missing_native_args",
    "SDK request arrived while BCAL callbacks are active or fenced.": "request_callback_fence",
    "SDK upstream model-request budget exhausted.": "request_budget",
    "SDK token usage must be a finite, nonnegative integer.": "invalid_token_usage",
    "SDK cost usage must be finite and nonnegative.": "invalid_cost_usage",
}


class CodingPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: Literal["gpt-56-reasoning-sol", "gpt-56-ceres", "gpt-55-chat"]
    reasoning_effort: Literal["none", "medium", "unset"]
    auxiliary: Literal["forbid"]

    @property
    def applied_effort(self) -> Literal["none", "medium"] | None:
        return None if self.reasoning_effort == "unset" else self.reasoning_effort

    @property
    def wire_effort(self) -> dict:
        # The pinned native runtime generates medium when its config option is absent.
        return {"presence": "explicit", "value": self.applied_effort or "medium"}

    def receipt(self) -> dict:
        return {
            "model": self.model,
            "runtime": "copilot-sdk",
            "requestedEffort": self.reasoning_effort,
            "appliedSdkEffort": self.applied_effort,
            "sdkOptionPresent": self.applied_effort is not None,
            "expectedWireEffort": self.wire_effort,
            "auxiliaryPolicy": self.auxiliary,
        }

    def verify_wire(self, body: dict) -> None:
        if body.get("model") != self.model or "reasoning_effort" in body or effort(body, "responses") != self.wire_effort:
            raise AdmissionError("Main model or pinned native wire effort differs from the explicit policy.")
        if body.get("parallel_tool_calls") is not False:
            raise AdmissionError("Production native parallel-tool guard was not observed.")


class CodingRun(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policies: tuple[CodingPolicy, ...] = Field(min_length=1, max_length=3)
    max_provider_attempts: int = Field(strict=True, gt=0)
    timeout_seconds: int = Field(strict=True, gt=30)
    page: int = Field(strict=True, gt=0)
    audience: Literal["Technical"] = "Technical"


class AdmissionError(RuntimeError):
    pass


class HasStatus(Protocol):
    status_code: int


class ProviderBudget:
    def __init__(self, path: Path, limit: int) -> None:
        if type(limit) is not int or limit <= 0:
            raise ValueError("An explicit positive provider-attempt ceiling is required.")
        self.path, self.limit = path, limit
        self.events: list[dict] = []
        self.seen: set[str] = set()
        self.stopped = False
        self.blocked = 0
        self.lock = threading.RLock()
        with path.open("x", encoding="utf-8") as file:
            json.dump(self.snapshot(), file)

    def snapshot(self) -> dict:
        return {"limit": self.limit, "attempts": len(self.events), "blocked": self.blocked, "stopped": self.stopped, "events": self.events}

    def reject(self, category: str) -> None:
        with self.lock:
            self.stopped = True
            self.blocked += 1
            write_json(self.path, self.snapshot())
        raise AdmissionError(category)

    def fail(self) -> None:
        with self.lock:
            self.stopped = True
            write_json(self.path, self.snapshot())

    def send[T: HasStatus](self, role: str, body: dict, operation: Callable[[], T]) -> T:
        fingerprint = hashlib.sha256(json.dumps({"role": role, "body": body}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        # Hold through the send: one actual provider request at a time across all routes.
        with self.lock:
            if self.stopped or fingerprint in self.seen or len(self.events) >= self.limit:
                self.reject("Provider budget exhausted, stopped, or identical request retry blocked.")
            self.seen.add(fingerprint)
            event = {
                "attempt": len(self.events) + 1,
                "role": role,
                "requestSha256": fingerprint,
                "model": body["model"],
                "wireEffort": effort(body, "responses" if role == "main" else "chat-completions"),
                "startedAtUtc": datetime.now(UTC).isoformat(),
                "outcome": "reserved",
            }
            self.events.append(event)
            write_json(self.path, self.snapshot())
            try:
                response = operation()
            except Exception:
                event["outcome"] = "transport_failure"
                self.fail()
                raise
            event.update(outcome="response_headers", httpStatus=response.status_code)
            if response.status_code != 200:
                self.stopped = True
            write_json(self.path, self.snapshot())
            return response


class ObservedResponse:
    def __init__(self, response: httpx.Response, budget: ProviderBudget, stream: bool) -> None:
        self.response, self.budget, self.stream = response, budget, stream
        self.status_code, self.headers = response.status_code, response.headers
        self.completed = False

    def iter_bytes(self) -> Iterator[bytes]:
        data = bytearray()
        try:
            for chunk in self.response.iter_bytes():
                if len(data) + len(chunk) > 16 * 1024 * 1024:
                    self.budget.reject("Provider response exceeded bounded observation size.")
                data.extend(chunk)
                yield chunk
            observed = safe_response(self.status_code, bytes(data), self.stream and self.status_code == 200)
            self.budget.events[-1]["response"] = observed
            self.completed = True
            if not observed["responseSuccess"]:
                self.budget.stopped = True
            write_json(self.budget.path, self.budget.snapshot())
        except Exception:
            self.budget.fail()
            raise

    def close(self) -> None:
        self.response.close()


class JudgeRequestError(RuntimeError):
    pass


def single_attempt_judge(complete: Callable, record: Callable[[dict], None]) -> Callable:
    entered = False

    def call(*args: object, **kwargs: object) -> object:
        nonlocal entered
        if entered:
            raise JudgeRequestError("Repeated judge callback blocked before inference.")
        entered = True
        record({"phase": "client", "outcome": "started"})
        try:
            return complete(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - prevent scorer-level retries and redact private client errors
            from openai import APIStatusError

            event = {"phase": "client", "outcome": "failed", "category": "http_status" if isinstance(error, APIStatusError) else "client_failure"}
            if isinstance(error, APIStatusError):
                event["httpStatus"] = error.status_code
            record(event)
            # autoevals.run_cached_request retries RateLimitError independently of OpenAI.
            raise JudgeRequestError("Single-attempt judge request failed.") from None

    return call


def score_checklist(job: dict, client: OpenAI, record: Callable[[dict], None]) -> dict:
    from autoevals.oai import LLMClient

    source = Path(importlib.metadata.distribution("bc-eval").locate_file("bc_eval/scorers/autoeval/lmchecklist.py"))
    if hashlib.sha256(source.read_bytes()).hexdigest() != SCORER_SHA:
        raise AdmissionError("Pinned ordinary judge scorer differs.")
    module = load_module("reasoning_coding_checklist", source)
    if module._JUDGE_MODEL != "gpt-56-ceres":
        raise AdmissionError("Ordinary judge model must remain Ceres.")
    transport = load_module("reasoning_coding_validation", ROOT / "scripts" / "bcal_study_transport.py")

    def complete(*args: object, **kwargs: object) -> object:
        if kwargs.get("model") != "gpt-56-ceres" or "reasoning_effort" in kwargs or "reasoning" in kwargs:
            raise AdmissionError("Judge policy must use Ceres with true omitted effort.")
        response = client.chat.completions.create(*args, **kwargs)
        transport.validate_judge_response(response.model_dump_json(exclude_none=True), job["expected"]["assertions"], record)
        return response

    wrapped = single_attempt_judge(complete, record)
    judge_client = LLMClient(openai=client, complete=wrapped)
    judge_client.complete = wrapped
    scorer = module.LmChecklist(client=judge_client)
    scores = scorer.eval(input=job["input"], output=job["output"], expected=job["expected"], metadata={})
    if any(score.metadata.get("error") for score in scores):
        raise JudgeRequestError("Malformed judge result is not a quality failure.")
    values = {score.name: score.score for score in scores}
    return {"quality": values["pass_rate"], "testPassed": values["test_passed"] == 1}


def process_environment() -> dict[str, str]:
    # The coding subprocess gets no BC connection, provider credential, or inherited BCAL overrides.
    names = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "DOTNET_ROOT",
        "DOTNET_ROOT_X64",
        "DOTNET_MULTILEVEL_LOOKUP",
        "PROCESSOR_ARCHITECTURE",
        "NUMBER_OF_PROCESSORS",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in names}


def coding_command(package: Path, symbols: Path, scenario: Path, private: Path, policy: CodingPolicy, run: CodingRun, base_url: str) -> tuple[list[str], BCalBackendConfig]:
    from bcbench.agent.bcal.agent import BCalBackendConfig
    from bcbench.types import BCalAgentPlanning, BCalAgentRuntime

    config = BCalBackendConfig(
        command=subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve()), "forbid-auxiliary", "--output", str(private / "auxiliary")]),
        model=policy.model,
        agent_runtime=BCalAgentRuntime.COPILOT_SDK,
        agent_planning=BCalAgentPlanning.COPILOT,
        sdk_provider="openai",
        sdk_base_url=base_url + "/v1",
        sdk_model=policy.model,
        sdk_api_key_env="BCAL_REASONING_LOCAL_KEY",
        sdk_reasoning_effort=policy.applied_effort,
        sdk_max_model_requests=run.max_provider_attempts,
        sdk_timeout_seconds=run.timeout_seconds - 30,
        inference_provider="bc-eval-m365-test@0.6.1",
        llm_provider="disabled-by-explicit-policy",
        llm_wire_api="chat-completions",
    )
    command = [
        str(package / "bcal.exe"),
        *config.cli_args(),
        f"--packagecachepath={symbols}",
        f"--scenario={scenario}",
        f"--result={private / 'result.json'}",
        "--include-evidence",
        f"--exportfolder={private / 'exports'}",
        f"--page={run.page}",
        f"--audience={run.audience}",
    ]
    return command, config


def verify_auxiliary_command(environment: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory(prefix="bcal-forbidden-aux-") as directory:
        output = Path(directory)
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "forbid-auxiliary", "--output", str(output)],
            env=environment,
            input="{}",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        receipts = list(output.glob("*.json"))
        if result.returncode != 1 or result.stdout or len(receipts) != 1 or json.loads(receipts[0].read_bytes()) != {"role": "auxiliary", "outcome": "forbidden", "providerAttempts": 0}:
            raise AdmissionError("The forbidden-auxiliary command did not pass its offline self-test.")


@contextmanager
def provider_route(policy: CodingPolicy | None, budget: ProviderBudget, key: str) -> Iterator[str]:
    from azure.identity import CertificateCredential, get_bearer_token_provider
    from bc_eval.llm.llm_api import ENDPOINTS, SCOPE, LlmApiSettings, LlmApiTransport, httpx, taxonomy_headers

    settings = LlmApiSettings.from_env()
    if settings.environment != "TEST":
        raise AdmissionError("Only the TEST provider is admitted.")
    client_source = Path(importlib.metadata.distribution("bc-eval").locate_file("bc_eval/llm/llm_api.py"))
    if hashlib.sha256(client_source.read_bytes()).hexdigest() != CLIENT_SHA:
        raise AdmissionError("Pinned inference client differs.")
    proxy = load_module("reasoning_coding_proxy", ROOT / "src" / "bcbench" / "agent" / "bcal" / "bc_eval_sdk_proxy.py")
    role, wire = ("main", "responses") if policy else ("judge", "chat-completions")
    model = policy.model if policy else "gpt-56-ceres"
    session = str(uuid.uuid4())

    class Boundary(httpx.BaseTransport):
        def __init__(self) -> None:
            self.inner = httpx.HTTPTransport(retries=0)
            self.ticket = ""

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            try:
                if policy:
                    policy.verify_wire(body)
                elif body.get("model") != model or "reasoning_effort" in body or "reasoning" in body:
                    budget.reject("Judge wire policy differs.")
                if any(request.headers.get(name) != "dev-" + model for name in ("X-ModelType", "x-llm-models")):
                    budget.reject("Provider model taxonomy differs.")
            except (AdmissionError, ValueError):
                budget.reject("Outbound model, taxonomy or effort mismatch.")
            request.headers.update({"X-SessionId": session, "X-InteractionId": session, "x-sticky-route-session-ticket": self.ticket})
            response = budget.send(role, body, lambda: self.inner.handle_request(request))
            self.ticket = response.headers.get("x-sticky-route-session-ticket", "")
            return response

        def close(self) -> None:
            self.inner.close()

    credential = CertificateCredential(settings.tenant_id, settings.client_id, certificate_path=os.environ["LLM_API_CERTIFICATE_FILE"], send_certificate_chain=True)
    token = get_bearer_token_provider(credential, SCOPE)
    with (
        credential,
        httpx.Client(
            transport=LlmApiTransport(settings, inner=Boundary()),
            headers=taxonomy_headers(settings, inference_step="HostAgent" if policy else "Judge"),
            follow_redirects=False,
            timeout=httpx.Timeout(90, connect=30),
        ) as client,
    ):

        @contextmanager
        def forward(route: str, body: dict) -> Iterator[ObservedResponse]:
            try:
                request = client.build_request("POST", ENDPOINTS["TEST"] + route, json=body, headers={"Authorization": "Bearer " + token()})
                with budget.lock, client.stream(request.method, request.url, headers=request.headers, content=request.content) as response:
                    observed = ObservedResponse(response, budget, bool(body.get("stream")))
                    try:
                        yield observed
                    finally:
                        if not observed.completed:
                            budget.fail()
            except Exception:  # noqa: BLE001 - stop and redact authentication, upstream and partial-stream failures
                budget.fail()
                raise proxy.ProxyError("Opt-in provider transport failed; run stopped.") from None

        class Handler(proxy._handler(key, model, wire, forward)):
            def _error(self, status: int, message: str) -> None:
                budget.fail()
                super()._error(status, message)

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                yield f"http://127.0.0.1:{server.server_port}"
            finally:
                server.shutdown()
                thread.join()


def validate_scenario(path: Path) -> bytes:
    data = path.read_bytes()
    scenario = json.loads(data)
    if (
        not isinstance(scenario, dict)
        or set(scenario) != {"schemaVersion", "steps"}
        or scenario["schemaVersion"] != "1.0"
        or not isinstance(scenario["steps"], list)
        or len(scenario["steps"]) != 1
        or not isinstance(step := scenario["steps"][0], dict)
        or set(step) != {"id", "type", "text"}
        or step["type"] != "user"
        or not isinstance(step["id"], str)
        or not step["id"]
        or not isinstance(step["text"], str)
        or not step["text"].strip()
    ):
        raise AdmissionError("Coding smoke requires exactly one explicit user step; no plan actions or fixture overrides.")
    return data


def transcript_summary(path: Path) -> dict:
    if not path.is_file():
        return {"available": False}
    try:
        body = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return {"available": False, "readOutcome": "invalid"}
    if not isinstance(body, dict):
        return {"available": False, "readOutcome": "invalid"}
    identity = body.get("runtimeIdentity")
    evidence = body.get("agentRuntimeEvidence")
    exported = body.get("export")
    failure = body.get("failure")
    failure_code = failure.get("code") if isinstance(failure, dict) else None
    turns = []
    for turn in evidence if isinstance(evidence, list) else []:
        if not isinstance(turn, dict):
            continue
        safe = {
            key: value
            for key, value in turn.items()
            if key
            in {
                "modelRequests",
                "responseIterations",
                "toolCalls",
                "usageEvents",
                "inputTokens",
                "outputTokens",
                "reasoningTokens",
                "cachedInputTokens",
                "domainCompleted",
                "mutationSucceeded",
                "compileSucceeded",
                "hasUncompiledMutation",
                "compileCoversLatestChange",
            }
            and (type(value) is bool or (type(value) is int and value >= 0))
        }
        terminal = turn.get("terminalState")
        safe["terminalState"] = terminal if isinstance(terminal, str) and terminal in TERMINAL_STATES else "unknown"
        turns.append(safe)
    return {
        "available": True,
        "completed": body.get("completed") is True,
        "failurePresent": body.get("failure") is not None,
        "failureCode": failure_code if isinstance(failure_code, str) and failure_code in FAILURE_CODES else "unknown" if failure is not None else None,
        "failureMessageSignature": FAILURE_SIGNATURES.get(failure.get("message"), "unknown") if isinstance(failure, dict) and isinstance(failure.get("message"), str) else None,
        "runtimeIdentityAvailable": isinstance(identity, dict),
        "runtimeModel": identity.get("mainModel") if isinstance(identity, dict) and identity.get("mainModel") in MODELS else None,
        "runtimeAppliedEffort": identity.get("reasoningEffort") if isinstance(identity, dict) and identity.get("reasoningEffort") in (None, "none", "medium") else None,
        "turns": turns,
        "exportAttempted": isinstance(exported, dict) and exported.get("attempted") is True,
        "exportSucceeded": isinstance(exported, dict) and exported.get("success") is True,
        "transcriptSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def run_coding(args: argparse.Namespace) -> None:
    from bcal_governed_study import verify_owned_cleanup
    from bcbench_core.agent.experiment import ExperimentConfiguration

    from bcbench.agent.bcal.agent import _read_transcript, _require_completed, _result_metrics, _run_bcal_process

    config_bytes = args.config.read_bytes()
    run = CodingRun.model_validate_json(config_bytes)
    if len({policy.model for policy in run.policies}) != len(run.policies):
        raise AdmissionError("Each selected model may run once; no replacement arms.")
    scenario_bytes = validate_scenario(args.scenario)
    verified = verify_package(args.package, args.archive)
    symbols = sorted(args.symbols.glob("*.app"))
    if not symbols:
        raise AdmissionError("An explicit local symbol cache is required.")
    args.output.mkdir(parents=True, exist_ok=False)
    frozen_scenario = args.output / "private" / "scenario.json"
    frozen_scenario.parent.mkdir()
    frozen_scenario.write_bytes(scenario_bytes)
    receipt = {
        "status": "prepared",
        "benchCommit": os.environ.get("GITHUB_SHA"),
        "pythonVersion": sys.version.split()[0],
        "packageSha256": PACKAGE_SHA,
        "packageSource": PACKAGE_SOURCE,
        "verifiedRuntimeFiles": verified,
        "configSha256": hashlib.sha256(config_bytes).hexdigest(),
        "scenarioSha256": hashlib.sha256(scenario_bytes).hexdigest(),
        "symbols": [{"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size} for path in symbols],
        "policies": [policy.receipt() for policy in run.policies],
        "maxProviderAttempts": run.max_provider_attempts,
        "scoring": "not-requested",
        "arms": [],
    }
    write_json(args.output / "receipt.json", receipt)
    if not args.execute:
        return
    budget = ProviderBudget(args.output / "provider-attempts.json", run.max_provider_attempts)
    try:
        verify_auxiliary_command(process_environment())
        for policy in run.policies:
            private = args.output / policy.model
            (private / "auxiliary").mkdir(parents=True)
            key = secrets.token_urlsafe(32)
            # cli_args verifies presence, never embeds the secret in argv.
            previous = os.environ.get("BCAL_REASONING_LOCAL_KEY")
            os.environ["BCAL_REASONING_LOCAL_KEY"] = key
            arm = {**policy.receipt(), "status": "started"}
            started = datetime.now(UTC)
            arm["startedAtUtc"] = started.isoformat()
            receipt["arms"].append(arm)
            write_json(args.output / "receipt.json", receipt)
            try:
                try:
                    with provider_route(policy, budget, key) as url:
                        command, config = coding_command(args.package, args.symbols, frozen_scenario, private, policy, run, url)
                        environment = {**process_environment(), "BCAL_REASONING_LOCAL_KEY": key}
                        with (private / "console.txt").open("w", encoding="utf-8") as console:
                            _run_bcal_process(command, timeout=run.timeout_seconds, stdout=console, env=environment)
                finally:
                    arm["runtimeCleanupVerified"] = False
                    verify_owned_cleanup(args.package / "bcal.exe")
                    arm["runtimeCleanupVerified"] = True
                if any((private / "auxiliary").iterdir()):
                    raise AdmissionError("Forbidden auxiliary legacy invocation occurred; no fallback is permitted.")
                transcript = _read_transcript(private / "result.json")
                if transcript.get("executionIdentity", {}).get("sourceCommitSha") != PACKAGE_SOURCE:
                    raise AdmissionError("Executed package source differs.")
                identity = transcript.get("runtimeIdentity", {})
                if identity.get("sdkPackageVersion") != "1.0.29" or identity.get("sdkRuntimeVersion") != "1.0.107":
                    raise AdmissionError("Executed native runtime differs.")
                experiment = config.experiment(run.timeout_seconds, transcript)
                if experiment.execution is None or not isinstance(auxiliary := experiment.execution.get("auxiliary"), dict):
                    raise AdmissionError("Explicit auxiliary execution identity is missing.")
                # Attribution must match the clean child environment, not a host review-model override.
                experiment = ExperimentConfiguration(execution={**experiment.execution, "auxiliary": {**auxiliary, "completionReviewModel": None}})
                _require_completed(transcript, metrics=_result_metrics(transcript, 0), config=experiment)
                if any(turn.get("compileCoversLatestChange") is not True for turn in transcript["agentRuntimeEvidence"]):
                    raise AdmissionError("Coding smoke requires compilation covering the latest source change.")
                events = [event for event in budget.events if event["model"] == policy.model and event["role"] == "main"]
                if budget.stopped or not events or any(event.get("httpStatus") != 200 for event in events):
                    raise AdmissionError("Successful coding requires complete, clean provider-attempt evidence.")
                if not any(path.is_file() for path in (private / "exports").rglob("*.al")):
                    raise AdmissionError("Actual coding must export AL source, not merely return a message.")
                arm.update(
                    status="completed",
                    runtimeAppliedEffort=identity.get("reasoningEffort"),
                    runtimeEffortFieldPresent="reasoningEffort" in identity,
                    providerAttempts=len(events),
                    observedWireEfforts=[event["wireEffort"] for event in events],
                    auxiliaryInvocations=0,
                    systemPromptSha256=identity.get("systemPromptSha256"),
                    toolCatalogSha256=identity.get("toolCatalogSha256"),
                    completed=True,
                    freshCompiled=True,
                    exportedAlFiles=len(list((private / "exports").rglob("*.al"))),
                    exportSourceHashes=[hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((private / "exports").rglob("*.al"))],
                )
            finally:
                arm.setdefault("auxiliaryInvocations", len(list((private / "auxiliary").iterdir())))
                arm.setdefault("providerAttempts", sum(event["model"] == policy.model and event["role"] == "main" for event in budget.events))
                arm.setdefault("observedWireEfforts", [event["wireEffort"] for event in budget.events if event["model"] == policy.model and event["role"] == "main"])
                if arm["status"] == "started":
                    arm["status"] = "failed"
                arm["finishedAtUtc"] = datetime.now(UTC).isoformat()
                arm["elapsedSeconds"] = (datetime.now(UTC) - started).total_seconds()
                observations = [event.get("response") for event in budget.events if event["model"] == policy.model and event["role"] == "main"]
                arm["responseObservations"] = observations
                arm["cost"] = None
                arm["terminalEvidence"] = transcript_summary(private / "result.json")
                if previous is None:
                    os.environ.pop("BCAL_REASONING_LOCAL_KEY", None)
                else:
                    os.environ["BCAL_REASONING_LOCAL_KEY"] = previous
        receipt["status"] = "completed"
    except Exception as error:
        budget.fail()
        receipt.update(status="failed", failureCategory=type(error).__name__)
        raise
    finally:
        receipt["accounting"] = budget.snapshot()
        write_json(args.output / "receipt.json", receipt)


def forbid_auxiliary(output: Path) -> None:
    write_json(output / f"{uuid.uuid4().hex}.json", {"role": "auxiliary", "outcome": "forbidden", "providerAttempts": 0})
    raise AdmissionError("Auxiliary inference is forbidden by the opt-in policy.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, epilog="Supported models: " + ", ".join(MODELS))
    commands = parser.add_subparsers(dest="command", required=True)
    coding = commands.add_parser("coding")
    for name in ("config", "package", "archive", "symbols", "scenario", "output"):
        coding.add_argument("--" + name, type=Path, required=True)
    coding.add_argument("--execute", action="store_true", help="Explicitly admit provider execution; otherwise prepare offline only.")
    forbidden = commands.add_parser("forbid-auxiliary")
    forbidden.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "forbid-auxiliary":
            forbid_auxiliary(args.output)
        run_coding(args)
    except ValidationError:
        sys.stderr.write("Invalid opt-in configuration: select an exact supported model, none/medium/unset effort, auxiliary=forbid, and explicit positive limits.\n")
        raise SystemExit(1) from None
    except AdmissionError as error:
        sys.stderr.write(f"Opt-in BCAL coding stopped: {error}\n")
        raise SystemExit(1) from None
    except Exception as error:  # noqa: BLE001 - public runner must not expose raw prompts, errors or credentials
        sys.stderr.write(f"Opt-in BCAL coding stopped: {type(error).__name__}\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
