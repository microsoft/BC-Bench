"""Memory-only governed model routing for local and hosted paired studies."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx2 as httpx


def load_proxy() -> ModuleType:
    source = Path(__file__).resolve().parents[1] / "src" / "bcbench" / "agent" / "bcal" / "bc_eval_sdk_proxy.py"
    spec = importlib.util.spec_from_file_location("governed_existing_sdk_proxy", source)
    if spec is None or spec.loader is None:
        raise ValueError("Existing BC-Bench SDK proxy is unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def exception_category(error: Exception) -> str:
    import httpx2 as httpx

    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    if isinstance(error, httpx.TransportError):
        return "transport"
    if isinstance(error, json.JSONDecodeError):
        return "json_decode"
    if isinstance(error, UnicodeError):
        return "body_decode"
    return "unknown"


@contextmanager
def forward_response(client: httpx.Client, request: httpx.Request, proxy_error: type[Exception], record: Callable[[dict], None]) -> Iterator[httpx.Response]:
    import httpx2 as httpx

    phase = "request"
    try:
        response = client.send(request, stream=True)
        phase = "body"
        record({"phase": "headers", "outcome": "received", "httpStatus": response.status_code})
        try:
            yield response
            record({"phase": "body", "outcome": "completed"})
        finally:
            response.close()
    except httpx.HTTPError as error:
        record({"phase": phase, "outcome": "failed", "category": exception_category(error)})
        raise proxy_error("Governed transport failed") from None
    except (BrokenPipeError, ConnectionResetError, TimeoutError):
        record({"phase": phase, "outcome": "failed", "category": "client_disconnect"})
        raise


def serve(args: argparse.Namespace) -> None:
    from azure.identity import CertificateCredential, get_bearer_token_provider
    from bc_eval.llm.llm_api import ENDPOINTS, SCOPE, LlmApiSettings, LlmApiTransport, httpx, taxonomy_headers

    proxy = load_proxy()
    ProxyError = proxy.ProxyError

    settings = LlmApiSettings.from_env()
    if settings.environment != "TEST":
        raise ValueError("This study only admits the TEST provider.")
    if (args.explicit_none_probe or args.required_reasoning_effort) and (args.model != "gpt-56-reasoning-sol" or args.step != "HostAgent"):
        raise ValueError("Explicit-none policy only admits the unchanged Sol main alias.")
    credential = CertificateCredential(settings.tenant_id, settings.client_id, certificate_path=os.environ["LLM_API_CERTIFICATE_FILE"], send_certificate_chain=True)
    token = get_bearer_token_provider(credential, SCOPE)
    session = str(uuid.uuid4())
    counts = {"requests": 0, "http200": 0, "ticketsReturned": 0, "ticketsReplayed": 0, "sessionStable": True, "modelStable": True}
    if args.explicit_none_probe:
        counts["explicitNoneVerifiedRequests"] = 0
    if args.required_reasoning_effort:
        counts.update(reasoningEffort=args.required_reasoning_effort, effortVerifiedRequests=0, effortRejectedRequests=0)
    diagnostics = {"schemaVersion": 1, "events": []}
    diagnostic_lock = Lock()
    retain_diagnostics = args.step == "HostAgent" and args.wire_api == "chat-completions" and os.environ.get("BCAL_AGENT_RUNTIME") == "legacy"

    def record(event: dict) -> None:
        if retain_diagnostics:
            with diagnostic_lock:
                diagnostics["events"].append({"observedAtUtc": datetime.now(UTC).isoformat(), "requestsObserved": counts["requests"], **event})
                write_json(args.audit.with_suffix(".diagnostics.json"), diagnostics)

    class Affinity(httpx.BaseTransport):
        def __init__(self) -> None:
            self.inner = httpx.HTTPTransport()
            self.ticket = ""
            self.lock = Lock()

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            with self.lock:
                body = json.loads(request.content)
                expected = "dev-" + args.model
                if body.get("model") != args.model or request.headers.get("X-ModelType") != expected or request.headers.get("x-llm-models") != expected:
                    counts["modelStable"] = False
                    write_json(args.audit, counts)
                    record({"phase": "guard", "outcome": "failed", "category": "model_mismatch"})
                    raise ProxyError("Governed model routing mismatch")
                if args.explicit_none_probe:
                    effort_matches = (
                        body.get("reasoning_effort") == "none" and "reasoning" not in body
                        if args.wire_api == "chat-completions"
                        else body.get("reasoning") == {"effort": "none"} and "reasoning_effort" not in body
                    )
                    if not effort_matches or not body.get("tools") or "tool_choice" in body or counts["requests"]:
                        raise ProxyError("Explicit-none probe outbound policy mismatch")
                    counts["explicitNoneVerifiedRequests"] += 1
                if args.required_reasoning_effort:
                    reasoning = body.get("reasoning")
                    matches = (
                        body.get("reasoning_effort") == args.required_reasoning_effort and "reasoning" not in body
                        if args.wire_api == "chat-completions"
                        else isinstance(reasoning, dict) and reasoning.get("effort") == args.required_reasoning_effort and "reasoning_effort" not in body
                    )
                    if not matches:
                        counts["effortRejectedRequests"] += 1
                        write_json(args.audit, counts)
                        record({"phase": "guard", "outcome": "failed", "category": "effort_mismatch"})
                        raise ProxyError("Governed outbound reasoning effort mismatch")
                    counts["effortVerifiedRequests"] += 1
                request.headers["X-SessionId"] = session
                request.headers["X-InteractionId"] = session
                request.headers["x-sticky-route-session-ticket"] = self.ticket
                counts["requests"] += 1
                counts["ticketsReplayed"] += bool(self.ticket)
                write_json(args.audit, counts)
                response = self.inner.handle_request(request)
                if response.status_code == 200:
                    counts["http200"] += 1
                self.ticket = response.headers.get("x-sticky-route-session-ticket", "")
                counts["ticketsReturned"] += bool(self.ticket)
                write_json(args.audit, counts)
                return response

        def close(self) -> None:
            self.inner.close()

    headers = taxonomy_headers(settings, inference_step=args.step)
    with credential, httpx.Client(transport=LlmApiTransport(settings, inner=Affinity()), headers=headers, timeout=httpx.Timeout(90 if args.step == "Judge" else 240, connect=30)) as client:

        @contextmanager
        def forward(route: str, body: dict[str, object]) -> Iterator:
            request = client.build_request("POST", ENDPOINTS["TEST"] + route, json=body, headers={"Authorization": "Bearer " + token()})
            with forward_response(client, request, ProxyError, record) as response:
                yield response

        write_json(args.audit, counts)
        if retain_diagnostics:
            write_json(args.audit.with_suffix(".diagnostics.json"), diagnostics)
        with ThreadingHTTPServer(("127.0.0.1", 0), proxy._handler(os.environ["BCAL_SDK_PROXY_KEY"], args.model, args.wire_api, forward)) as server:
            write_json(args.ready, {"base_url": f"http://127.0.0.1:{server.server_port}", "pid": os.getpid()})
            server.serve_forever()


def bridge_response_shape(response: str) -> str:
    try:
        body = json.loads(response)
    except json.JSONDecodeError:
        return "invalid_json"
    if not isinstance(body, dict):
        return "invalid_object"
    choices = body.get("choices")
    if not isinstance(choices, list):
        return "missing_choices"
    if not choices:
        return "empty_choices"
    if not isinstance(choices[0], dict) or not isinstance(choices[0].get("message"), dict):
        return "missing_message"
    return "message_present"


def bridge() -> None:
    directory = os.environ.get("BCAL_STUDY_BRIDGE_DIAGNOSTICS")
    path = Path(directory) / f"bridge-{uuid.uuid4().hex}.json" if directory else None
    events = []

    def record(event: dict) -> None:
        if path is not None:
            events.append({"observedAtUtc": datetime.now(UTC).isoformat(), **event})
            write_json(path, {"schemaVersion": 1, "events": events})

    record({"phase": "command", "outcome": "started"})
    try:
        _bridge(record)
    except Exception as error:
        record({"phase": "command", "outcome": "failed", "category": exception_category(error)})
        raise


def _bridge(record: Callable[[dict], None]) -> None:
    from openai import OpenAI

    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (ValueError, UnicodeError) as error:
        record({"phase": "input", "outcome": "failed", "category": exception_category(error)})
        raise
    if request.get("model") != os.environ.get("BCAL_LLM_MODEL", "gpt-55-chat") or not isinstance(request.get("messages"), list):
        raise ValueError("Unexpected external-command model or messages.")
    effort = os.environ.get("BCAL_STUDY_REASONING_EFFORT")
    if effort is not None and (effort != "none" or request["model"] != "gpt-56-reasoning-sol"):
        raise ValueError("Only the governed explicit-none Sol policy is admitted.")
    if request["model"] == "gpt-56-reasoning-sol" and request.get("reasoning_effort") not in (None, effort):
        raise ValueError("Incoming Sol reasoning effort conflicts with the governed policy.")
    kwargs = {key: request[key] for key in ("model", "messages", "tools", "reasoning_effort", "max_completion_tokens") if key in request}
    if kwargs.get("reasoning_effort") is None:
        kwargs.pop("reasoning_effort", None)
    if effort is not None:
        kwargs["reasoning_effort"] = effort
    kwargs.setdefault("max_completion_tokens", 16384)
    with OpenAI(base_url=os.environ["BCAL_STUDY_CHAT_URL"] + "/v1", api_key=os.environ["BCAL_SDK_PROXY_KEY"], max_retries=0, timeout=240) as client:
        record({"phase": "client", "outcome": "started"})
        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as error:
            from openai import APIConnectionError, APIResponseValidationError, APIStatusError, APITimeoutError

            category = exception_category(error)
            diagnostic = {"phase": "client", "outcome": "failed", "category": category}
            if isinstance(error, APIStatusError):
                diagnostic.update(category="http_status", httpStatus=error.status_code)
            elif isinstance(error, APITimeoutError):
                diagnostic["category"] = "timeout"
            elif isinstance(error, APIConnectionError):
                diagnostic["category"] = "transport"
            elif isinstance(error, APIResponseValidationError):
                diagnostic["category"] = "response_validation"
            record(diagnostic)
            raise
        try:
            encoded = response.model_dump_json(exclude_none=True)
        except Exception as error:
            record({"phase": "serialization", "outcome": "failed", "category": exception_category(error)})
            raise
        record({"phase": "response", "outcome": bridge_response_shape(encoded)})
        try:
            sys.stdout.write(encoded)
        except OSError:
            record({"phase": "output", "outcome": "failed", "category": "command_io"})
            raise
        record({"phase": "command", "outcome": "emitted"})


def judge(args: argparse.Namespace) -> None:
    import hashlib

    from autoevals.oai import LLMClient
    from openai import OpenAI

    source = Path(importlib.metadata.distribution("bc-eval").locate_file("bc_eval/scorers/autoeval/lmchecklist.py"))
    expected_hash = "c563e569520b202e725d46ac58497868fefd8d48662fb8a305c9a397e14c398d"
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("Unchanged checklist scorer hash mismatch.")
    os.environ["JUDGE_MODEL"] = "gpt-56-ceres"
    spec = importlib.util.spec_from_file_location("governed_unchanged_checklist", source)
    if spec is None or spec.loader is None:
        raise ValueError("Checklist module unavailable.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    job = json.loads(args.input.read_bytes())
    with OpenAI(base_url=os.environ["BCAL_STUDY_CHAT_URL"] + "/v1", api_key=os.environ["BCAL_SDK_PROXY_KEY"], max_retries=0, timeout=90) as client:
        scorer = module.LmChecklist(client=LLMClient(openai=client, complete=client.chat.completions.create))
        scores = scorer.eval(input=job["input"], output=job["output"], expected=job["expected"], metadata={})
    values = {score.name: score.score for score in scores}
    assertions = next(score.metadata["assertions"] for score in scores if score.name == "pass_rate")
    if any(type(assertion.get("pass")) is not bool for assertion in assertions) or len(assertions) != len(job["expected"]["assertions"]):
        raise ValueError("Incomplete checklist results.")
    if any(score.metadata.get("error") for score in scores):
        raise ValueError("Malformed judge response is not a quality failure.")
    write_json(args.output, {"quality": values["pass_rate"], "testPassed": values["test_passed"] == 1, "assertionPass": [item["pass"] for item in assertions]})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    server = commands.add_parser("serve")
    server.add_argument("--model", choices=("gpt-55-chat", "gpt-56-reasoning-sol", "gpt-56-ceres"), required=True)
    server.add_argument("--wire-api", choices=("responses", "chat-completions"), required=True)
    server.add_argument("--step", choices=("HostAgent", "Judge"), required=True)
    server.add_argument("--ready", type=Path, required=True)
    server.add_argument("--audit", type=Path, required=True)
    server.add_argument("--explicit-none-probe", action="store_true")
    server.add_argument("--required-reasoning-effort", choices=("none",))
    commands.add_parser("bridge")
    scorer = commands.add_parser("judge")
    scorer.add_argument("--input", type=Path, required=True)
    scorer.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        {"serve": serve, "bridge": lambda _: bridge(), "judge": judge}[args.command](args)
    except Exception as error:  # noqa: BLE001 - redact private upstream bodies at the public-log boundary
        # Model text, authorization headers and upstream bodies must not reach public job logs.
        sys.stderr.write(f"Governed {args.command} failed: {type(error).__name__}\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
