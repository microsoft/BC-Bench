"""Loopback-only, authenticated evaluation transport; model requests are not translated."""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Protocol, override, runtime_checkable

logger = logging.getLogger(__name__)
_MAX_REQUEST_BYTES = 16 * 1024 * 1024
_KEY_ENV = "BCAL_SDK_PROXY_KEY"


@runtime_checkable
class UpstreamResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def iter_bytes(self) -> Iterator[bytes]: ...

    def close(self) -> None: ...


type ForwardRequest = Callable[[str, dict[str, object]], AbstractContextManager[UpstreamResponse]]


class ProxyError(Exception):
    pass


def _handler(key: str, model: str, wire_api: str, forward: ForwardRequest) -> type[BaseHTTPRequestHandler]:
    route = {"responses": "/responses", "chat-completions": "/chat/completions"}[wire_api]

    class Handler(BaseHTTPRequestHandler):
        @override
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(30)

        @override
        def log_message(self, format: str, *args: object) -> None:
            # BaseHTTPRequestHandler includes request text in its access log.
            logger.debug("Evaluation proxy request completed")

        def _authorized(self) -> bool:
            return hmac.compare_digest(self.headers.get("Authorization", "").encode(), f"Bearer {key}".encode())

        def _reply_json(self, status: int, value: dict[str, object]) -> None:
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str) -> None:
            self._reply_json(status, {"error": {"message": message}})

        def do_GET(self) -> None:
            if not self._authorized():
                self._error(401, "Local proxy authentication required")
            elif self.path == "/health":
                self._reply_json(200, {"status": "ready", "wireApi": wire_api, "model": model})
            else:
                self._error(404, "Unsupported evaluation endpoint")

        def do_POST(self) -> None:
            if not self._authorized():
                self._error(401, "Local proxy authentication required")
                return
            if self.path not in (route, f"/v1{route}"):
                self._error(404, "Unsupported evaluation endpoint")
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._error(400, "Invalid Content-Length")
                return
            if not 0 < size <= _MAX_REQUEST_BYTES:
                self._error(413, "Request body must be between 1 byte and 16 MiB")
                return
            try:
                data = self.rfile.read(size)
                if len(data) != size:
                    self._error(400, "Incomplete request body")
                    return
                body = json.loads(data)
            except (ValueError, UnicodeError):
                self._error(400, "Request body must be JSON")
                return
            if not isinstance(body, dict) or body.get("model") != model:
                self._error(400, "Request must use the configured evaluation model")
                return

            started = False
            try:
                with forward(route, body) as response:
                    self.send_response(response.status_code)
                    self.send_header("Content-Type", response.headers.get("content-type", "application/json"))
                    for header in ("retry-after", "x-request-id", "request-id"):
                        if (value := response.headers.get(header)) is not None:
                            self.send_header(header, value)
                    self.send_header("Connection", "close")
                    self.end_headers()
                    started = True
                    for chunk in response.iter_bytes():
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except ProxyError:
                logger.exception("Evaluation inference transport failed")
                if not started:
                    self._error(502, "Evaluation inference transport failed")
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                logger.warning("Evaluation inference client disconnected")
            finally:
                self.close_connection = True

    return Handler


def _create_forwarder() -> tuple[ForwardRequest, Callable[[], None]]:
    from azure.core.exceptions import AzureError
    from azure.identity import CertificateCredential, get_bearer_token_provider
    from bc_eval.llm.auth import get_certificate_credential
    from bc_eval.llm.llm_api import ENDPOINTS, SCOPE, LlmApiSettings, LlmApiTransport, httpx, taxonomy_headers

    settings = LlmApiSettings.from_env()
    if cert := os.environ.get("LLM_API_CERTIFICATE_FILE"):
        credential = CertificateCredential(settings.tenant_id, settings.client_id, certificate_path=cert, send_certificate_chain=True)
    else:
        credential = get_certificate_credential(
            tenant_id=settings.tenant_id,
            client_id=settings.client_id,
            key_vault_name=settings.certificate_key_vault,
            cert_name=settings.certificate_name,
        )
    token = get_bearer_token_provider(credential, SCOPE)
    session_id = str(uuid.uuid4())

    class AffinityTransport(httpx.BaseTransport):
        def __init__(self) -> None:
            self.inner = httpx.HTTPTransport()
            self.ticket = ""
            self.lock = Lock()

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            with self.lock:
                request.headers["X-SessionId"] = session_id
                request.headers["x-sticky-route-session-ticket"] = self.ticket
            response = self.inner.handle_request(request)
            if (ticket := response.headers.get("x-sticky-route-session-ticket")) is not None:
                with self.lock:
                    self.ticket = ticket
            return response

        def close(self) -> None:
            self.inner.close()

    client = httpx.Client(
        transport=LlmApiTransport(settings, inner=AffinityTransport()),
        headers={**taxonomy_headers(settings, inference_step="HostAgent"), "x-sticky-route-session-ticket": ""},
        timeout=httpx.Timeout(240, connect=60),
    )

    @contextmanager
    def forward(route: str, body: dict[str, object]) -> Iterator[UpstreamResponse]:
        try:
            request = client.build_request("POST", f"{ENDPOINTS[settings.environment]}{route}", json=body, headers={"Authorization": f"Bearer {token()}"})
            response = client.send(request, stream=True)
            try:
                if not isinstance(response, UpstreamResponse):
                    raise ProxyError("Unsupported upstream response type")
                yield response
            finally:
                response.close()
        except (AzureError, httpx.HTTPError) as error:
            # Do not log request headers, credentials, or upstream bodies.
            raise ProxyError(f"Upstream request failed ({type(error).__name__})") from None

    def close() -> None:
        client.close()
        credential.close()

    return forward, close


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--wire-api", choices=("responses", "chat-completions"), required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()
    if not (key := os.environ.get(_KEY_ENV)):
        parser.error(f"{_KEY_ENV} is required")
    forward, close = _create_forwarder()
    try:
        with ThreadingHTTPServer(("127.0.0.1", args.port), _handler(key, args.model, args.wire_api, forward)) as server:
            args.ready_file.write_text(json.dumps({"base_url": f"http://127.0.0.1:{server.server_port}", "pid": os.getpid()}), encoding="utf-8")
            server.serve_forever()
    finally:
        close()


if __name__ == "__main__":
    main()
