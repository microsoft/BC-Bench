"""Isolated synthetic compatibility diagnostic; never an evaluation/default policy."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
import secrets
import subprocess
import sys
import threading
import uuid
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager, redirect_stdout
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import httpx2 as httpx


class HasStatus(Protocol):
    status_code: int


ROOT = Path(__file__).resolve().parents[1]
MODELS = ("gpt-56-reasoning-sol", "gpt-56-ceres", "gpt-55-chat")
POLICIES = ("none", "medium", "omitted")
PACKAGE_SHA = "58690e69bb6969a350c24c098d2493e9a38ab3e86b2c6cff0ee6f1d88b09bb32"
CLIENT_SHA = "f4dfdd0148debfc2de8a3cabfa49b00c9f8b01bfcbfa4a78708c7d0459cfe815"
PROMPT = "Return OK or echo OK using compat_echo."
TOOL = {
    "name": "compat_echo",
    "description": "Echo a synthetic value.",
    "parameters": {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"], "additionalProperties": False},
}


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Diagnostic module unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def effort(body: dict, wire: str) -> dict:
    field = "reasoning_effort" if wire == "chat-completions" else "reasoning"
    if field not in body:
        return {"presence": "omitted"}
    value = body[field]
    if wire == "responses" and isinstance(value, dict):
        value = value.get("effort")
    if value not in (None, "none", "low", "medium", "high", "xhigh", "max"):
        raise ValueError("Non-allowlisted reasoning effort.")
    return {"presence": "null" if value is None else "explicit", "value": value}


class AdmissionError(Exception):
    pass


def discover_package(installed_root: Path, cache_root: Path) -> tuple[Path, Path]:
    binaries = [path for path in installed_root.rglob("bcal.dll") if path.parent.name == "any" and path.parent.parent.name == "net10.0"]
    archive_name = "microsoft.businesscentral.bcal.cli.30.0.46.49019-beta.nupkg"
    archives = list(installed_root.rglob(archive_name))
    cached = cache_root / archive_name
    if cached.is_file() and cached not in archives:
        archives.append(cached)
    if len(binaries) != 1 or not archives:
        raise AdmissionError("Exact installed binary or retained archive unavailable.")
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != PACKAGE_SHA for path in archives):
        raise AdmissionError("Retained archive differs from exact authorized package.")
    return binaries[0].parent, archives[0]


class AttemptBudget:
    def __init__(self, path: Path, limit: int = 24) -> None:
        if not 1 <= limit <= 24:
            raise ValueError("Diagnostic attempt ceiling must not exceed 24.")
        self.path = path
        self.limit = limit
        self.events: list[dict] = []
        self.cells: set[str] = set()
        self.blocked = 0
        self.lock = threading.Lock()
        with path.open("x", encoding="utf-8") as file:
            json.dump(self.snapshot(), file)

    def snapshot(self) -> dict:
        return {"limit": self.limit, "attempts": len(self.events), "blocked": self.blocked, "events": self.events}

    def send[T: HasStatus](self, cell: str, operation: Callable[[], T]) -> T:
        with self.lock:
            if cell in self.cells or len(self.events) >= self.limit:
                self.blocked += 1
                write_json(self.path, self.snapshot())
                raise AdmissionError("No retry/replacement or excess provider attempt admitted.")
            self.cells.add(cell)
            event = {"cell": cell, "attempt": len(self.events) + 1, "startedAtUtc": datetime.now(UTC).isoformat(), "outcome": "started"}
            self.events.append(event)
            # Persist reservation before the innermost, non-retrying HTTP transport.
            write_json(self.path, self.snapshot())
        try:
            response = operation()
        except Exception:
            with self.lock:
                event["outcome"] = "transport_failure"
                write_json(self.path, self.snapshot())
            raise
        with self.lock:
            event.update(outcome="response_headers", httpStatus=response.status_code)
            write_json(self.path, self.snapshot())
        return response


def admit(body: dict, model: str, wire: str, expected: dict) -> None:
    serialized = json.dumps(body).casefold()
    if any(marker in serialized for marker in ("business central", "bcal", "c:\\\\users", "c:\\\\src")):
        raise AdmissionError("Non-synthetic context rejected.")
    if body.get("model") != model or effort(body, wire) != expected:
        raise AdmissionError("Model or offline-established effort differs.")
    tools = body.get("tools")
    if not isinstance(tools, list) or len(tools) != 1:
        raise AdmissionError("Exactly one synthetic tool required.")
    tool = tools[0].get("function") if wire == "chat-completions" else tools[0]
    if not isinstance(tool, dict) or tool.get("name") != "compat_echo":
        raise AdmissionError("Non-synthetic tool rejected.")
    if "tool_choice" in body:
        raise AdmissionError("No forced/disabled tool selection admitted.")
    if wire == "chat-completions":
        if body.get("messages") != [{"role": "user", "content": PROMPT}]:
            raise AdmissionError("Only the synthetic Chat prompt is admitted.")
    elif body.get("parallel_tool_calls") is not False:
        raise AdmissionError("Production SDK handler did not disable parallel tools.")


def safe_response(status: int, data: bytes, stream: bool) -> dict:
    result: dict = {
        "httpStatus": status,
        "responseSuccess": False,
        "toolsAccepted": True if 200 <= status < 300 else None,
        "responseModel": None,
        "usage": None,
        "reasoningTokensAvailable": False,
        "responseShape": None,
    }
    try:
        if stream:
            payloads = [json.loads(line[5:].strip()) for line in data.decode("utf-8").splitlines() if line.startswith("data:") and line[5:].strip() != "[DONE]"]
            bodies = [item.get("response", item) for item in payloads if isinstance(item, dict)]
        else:
            bodies = [json.loads(data)]
    except (UnicodeError, ValueError):
        result.update(errorStage="response", errorCategory="body_decode")
        return result
    for body in bodies:
        if not isinstance(body, dict):
            continue
        if isinstance(body.get("model"), str):
            # Identity only, never response text/reasoning/error messages.
            result["responseModel"] = body["model"][:128]
        usage = body.get("usage")
        if isinstance(usage, dict):
            result["usage"] = {key: value for key, value in usage.items() if key in {"input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens"} and type(value) is int}
            result["reasoningTokensAvailable"] = False
            for key in ("output_tokens_details", "completion_tokens_details"):
                details = usage.get(key)
                if isinstance(details, dict) and type(details.get("reasoning_tokens")) is int:
                    result.update(reasoningTokensAvailable=True, reasoningTokens=details["reasoning_tokens"])
        choices = body.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            calls = message.get("tool_calls", [])
            result.update(
                responseSuccess=200 <= status < 300 and choices[0].get("finish_reason") in {"stop", "tool_calls"} and bool(message.get("content") or calls),
                responseShape="tool_calls" if calls else "message",
                toolCallCount=len(calls),
                toolArgumentsJsonValid=all(valid_arguments(call.get("function", {}).get("arguments")) for call in calls),
            )
        if isinstance(body.get("output"), list):
            calls = [item for item in body["output"] if item.get("type") == "function_call"]
            if body.get("status") in {"completed", "incomplete", "failed"}:
                result.update(
                    responseSuccess=200 <= status < 300 and body.get("status") == "completed" and any(item.get("type") in {"message", "function_call"} for item in body["output"]),
                    responseShape="function_call" if calls else "message",
                    toolCallCount=len(calls),
                    toolArgumentsJsonValid=all(valid_arguments(call.get("arguments")) for call in calls),
                )
    if not 200 <= status < 300:
        result.update(errorStage="provider", errorCategory="quota_or_throttle" if status == 429 else "contract_rejection" if status in {400, 422} else "http_status")
    elif not result["responseSuccess"]:
        result.update(errorStage="response", errorCategory="incomplete_or_unrecognized")
    return result


def valid_arguments(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return isinstance(json.loads(value), dict)
    except ValueError:
        return False


def legacy_bridge(model: str, policy: str, url: str, key: str) -> dict:
    from openai import OpenAI

    bridge = load_module("compatibility_production_bridge", ROOT / "src" / "bcbench" / "agent" / "bcal" / "bc_eval_llm_api_bridge.py")
    from bc_eval.llm import llm_api

    original = llm_api.create_llm_api_client
    client = OpenAI(base_url=url + "/v1", api_key=key, max_retries=0, timeout=100)
    llm_api.create_llm_api_client = lambda **_: client
    request = {"model": model, "messages": [{"role": "user", "content": PROMPT}], "tools": [{"type": "function", "function": TOOL}], "max_completion_tokens": 1024}
    if policy != "omitted":
        request["reasoning_effort"] = policy
    original_stdin = sys.stdin
    previous_cert = os.environ.pop("LLM_API_CERTIFICATE_FILE", None)
    try:
        with bridge.sticky_route_ticket_broker_environment() as environment:
            saved = {name: os.environ.get(name) for name in environment}
            os.environ.update(environment)
            sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(request).encode()), encoding="utf-8")
            try:
                with redirect_stdout(io.StringIO()):
                    bridge.main()
            finally:
                for name, value in saved.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value
    except Exception:  # noqa: BLE001 - record explicit failure without proprietary upstream error text
        return {"outcome": "bridge_failure"}
    else:
        return {"outcome": "response_parsed"}
    finally:
        sys.stdin = original_stdin
        llm_api.create_llm_api_client = original
        if previous_cert is not None:
            os.environ["LLM_API_CERTIFICATE_FILE"] = previous_cert
        client.close()


def native_command(package: Path, helper: Path, model: str, policy: str, url: str, output: Path) -> list[str]:
    return ["dotnet", "exec", "--depsfile", str(package / "bcal.deps.json"), "--runtimeconfig", str(package / "bcal.runtimeconfig.json"), str(helper), str(package), model, policy, url, str(output)]


def native_probe(package: Path, helper: Path, model: str, policy: str, url: str, output: Path, key: str) -> dict:
    try:
        completed = subprocess.run(native_command(package, helper, model, policy, url, output), env={**os.environ, "BCAL_SDK_PROXY_KEY": key}, capture_output=True, timeout=130, check=False)
    except subprocess.TimeoutExpired:
        return {"outcome": "process_timeout"}
    if completed.returncode != 0:
        return {"outcome": "process_failure"}
    return json.loads(output.read_bytes())


def verify_package(package: Path, archive_path: Path) -> int:
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != PACKAGE_SHA:
        raise AdmissionError("Package hash differs.")
    verified = 0
    with zipfile.ZipFile(archive_path) as archive:
        for item in archive.infolist():
            prefix = "tools/net10.0/any/"
            if item.filename.startswith(prefix) and not item.is_dir():
                relative = Path(item.filename[len(prefix) :])
                if relative.is_absolute() or ".." in relative.parts:
                    raise AdmissionError("Invalid archive path.")
                if hashlib.sha256(archive.read(item)).digest() != hashlib.sha256((package / relative).read_bytes()).digest():
                    raise AdmissionError("Actual packaged runtime file differs from pinned archive.")
                verified += 1
    if verified != 224:
        raise AdmissionError("Exact runtime inventory differs.")
    return verified


def run(args: argparse.Namespace) -> None:
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "admission.json").exists():
        raise AdmissionError("This diagnostic output is immutable; no rerun/replacement.")
    verified = verify_package(args.package, args.archive)
    import importlib.metadata

    client_source = Path(importlib.metadata.distribution("bc-eval").locate_file("bc_eval/llm/llm_api.py"))
    if hashlib.sha256(client_source.read_bytes()).hexdigest() != CLIENT_SHA:
        raise AdmissionError("Pinned client differs.")
    offline: dict[tuple[str, str], dict] = {}
    for model in MODELS:
        for policy in POLICIES:
            row = native_probe(args.package, args.helper, model, policy, "offline", args.output / f"offline-{model}-{policy}.json", "offline")
            offline[model, policy] = row
            if row.get("outcome") != "response_received" or row.get("boundaryRequests") != 1:
                raise AdmissionError("Native offline generation gate failed; no provider dispatch admitted.")
    admission = {
        "status": "offline_passed",
        "benchCommit": os.environ.get("GITHUB_SHA"),
        "packageSha256": PACKAGE_SHA,
        "packageVersion": "30.0.46.49019-beta",
        "packageSource": "52f3f7f5dd2d26c83f2778d28ace9d47364b481b",
        "sdkPackage": "1.0.29",
        "sdkRuntime": "1.0.107",
        "models": MODELS,
        "policies": POLICIES,
        "primaryCells": 18,
        "httpAttemptCap": 24,
        "perCellAttemptCap": 1,
        "maxConcurrentProviderRequests": 1,
        "verifiedRuntimeFiles": verified,
        "runnerSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "helperSha256": hashlib.sha256(args.helper.read_bytes()).hexdigest(),
        "noRetries": True,
        "scope": "Synthetic config; production bridge serializer and packaged SDK generation/full production handler; not full agent/evaluation parity.",
    }
    write_json(args.output / "admission.json", admission)
    if not args.execute:
        return
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise AdmissionError("Only the first hosted dispatch is admitted.")
    execute(args, offline, admission)


def execute(args: argparse.Namespace, offline: dict, admission: dict) -> None:
    from azure.identity import CertificateCredential, get_bearer_token_provider
    from bc_eval.llm.llm_api import SCOPE, LlmApiSettings

    settings = LlmApiSettings.from_env()
    if settings.environment != "TEST":
        raise AdmissionError("Only TEST admitted.")
    budget = AttemptBudget(args.output / "http-attempts.json")
    proxy = load_module("compatibility_proxy", ROOT / "src" / "bcbench" / "agent" / "bcal" / "bc_eval_sdk_proxy.py")
    rows: list[dict] = []
    credential = CertificateCredential(settings.tenant_id, settings.client_id, certificate_path=os.environ["LLM_API_CERTIFICATE_FILE"], send_certificate_chain=True)
    token = get_bearer_token_provider(credential, SCOPE)
    with credential:
        for model in MODELS:
            for policy in POLICIES:
                for runtime, wire in (("legacy-bridge", "chat-completions"), ("packaged-native", "responses")):
                    row = run_cell(args, model, policy, runtime, wire, offline[model, policy], budget, settings, token, proxy)
                    rows.append(row)
                    write_json(args.output / "matrix.json", {"admission": admission, "cells": rows, "accounting": budget.snapshot()})


def run_cell(args: argparse.Namespace, model: str, policy: str, runtime: str, wire: str, native: dict, budget: AttemptBudget, settings: object, token: Callable[[], str], proxy: ModuleType) -> dict:
    from azure.core.exceptions import AzureError
    from bc_eval.llm.llm_api import ENDPOINTS, LlmApiTransport, httpx, taxonomy_headers

    cell = f"{model}:{policy}:{runtime}"
    expected = (
        effort({"reasoning": native["wire"]["reasoning"]} if native["wire"]["effortPresent"] else {}, wire)
        if wire == "responses"
        else ({"presence": "omitted"} if policy == "omitted" else {"presence": "explicit", "value": policy})
    )
    row = {
        "cell": cell,
        "model": model,
        "runtime": runtime,
        "wireApi": wire,
        "requestedPolicy": policy,
        "appliedEffort": native.get("appliedEffort") if wire == "responses" else None if policy == "omitted" else policy,
        "expectedWireEffort": expected,
        "providerAttempts": 0,
    }
    session = str(uuid.uuid4())

    class Boundary(httpx.BaseTransport):
        def __init__(self) -> None:
            self.inner = httpx.HTTPTransport(retries=0)

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            admit(body, model, wire, expected)
            if request.headers.get("X-ModelType") != "dev-" + model or request.headers.get("x-llm-models") != "dev-" + model:
                raise AdmissionError("Pinned model taxonomy routing differs.")
            request.headers.update({"X-SessionId": session, "X-InteractionId": session, "x-sticky-route-session-ticket": ""})
            row["wireEffort"] = effort(body, wire)
            row["toolsSent"] = 1
            response = budget.send(cell, lambda: self.inner.handle_request(request))
            response.read()
            row.update(safe_response(response.status_code, response.content, bool(body.get("stream")) and response.status_code == 200))
            return response

        def close(self) -> None:
            self.inner.close()

    with httpx.Client(
        transport=LlmApiTransport(settings, inner=Boundary()), headers=taxonomy_headers(settings, inference_step="HostAgent"), follow_redirects=False, timeout=httpx.Timeout(90, connect=30)
    ) as client:

        @contextmanager
        def forward(route: str, body: dict) -> Iterator[httpx.Response]:
            try:
                request = client.build_request("POST", ENDPOINTS["TEST"] + route, json=body, headers={"Authorization": "Bearer " + token()})
                response = client.send(request)
                row["clientHttpStatus"] = response.status_code
                try:
                    yield response
                finally:
                    response.close()
            except AdmissionError:
                row.update(errorStage="local_admission", errorCategory="budget_or_wire_guard")
                raise proxy.ProxyError("Isolated diagnostic admission rejected") from None
            except AzureError:
                row.update(errorStage="authentication", errorCategory="authentication")
                raise proxy.ProxyError("Isolated diagnostic authentication failed") from None
            except httpx.HTTPError:
                row.update(errorStage="transport", errorCategory="transport")
                raise proxy.ProxyError("Isolated diagnostic transport failed") from None

        key = secrets.token_urlsafe(32)
        with ThreadingHTTPServer(("127.0.0.1", 0), proxy._handler(key, model, wire, forward)) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                if wire == "responses":
                    row["runtimeReceipt"] = native_probe(args.package, args.helper, model, policy, url, args.output / f"native-{model}-{policy}.json", key)
                else:
                    row["runtimeReceipt"] = legacy_bridge(model, policy, url, key)
            finally:
                server.shutdown()
                thread.join()
    row["providerAttempts"] = sum(event["cell"] == cell for event in budget.events)
    if not row["providerAttempts"]:
        row.setdefault("errorStage", "local_runtime")
        row.setdefault("errorCategory", "no_provider_request")
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        run(args)
    except Exception as error:  # noqa: BLE001 - public entrypoint must not expose raw private errors
        sys.stderr.write(f"Compatibility admission/execution failed ({type(error).__name__}); no corrective retry.\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
