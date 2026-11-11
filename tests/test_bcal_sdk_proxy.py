import json
from collections.abc import Iterator
from contextlib import closing, contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from bcbench.agent.bcal.bc_eval_sdk_proxy import ProxyError, _handler


class Response:
    def __init__(self, status=200, chunks=(b'{"status":"completed"}',), content_type="application/json"):
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.chunks = chunks

    def iter_bytes(self) -> Iterator[bytes]:
        yield from self.chunks

    def close(self) -> None:
        pass


@contextmanager
def proxy(response=None, failure=False):
    calls = []

    @contextmanager
    def forward(route, body):
        calls.append((route, body))
        if failure:
            raise ProxyError("upstream unavailable")
        yield response or Response()

    with ThreadingHTTPServer(("127.0.0.1", 0), _handler("local-secret", "test-model", "responses", forward)) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            yield server.server_port, calls
        finally:
            server.shutdown()
            thread.join()


def request(port, path="/responses", body=None, key="local-secret"):
    with closing(HTTPConnection("127.0.0.1", port, timeout=5)) as connection:
        connection.request("POST", path, json.dumps(body if body is not None else {"model": "test-model", "input": "hello"}), {"Authorization": f"Bearer {key}"})
        response = connection.getresponse()
        return response.status, response.read()


@pytest.mark.parametrize("path", ["/responses", "/v1/responses"])
def test_proxy_passes_requests_without_protocol_conversion(path):
    body = {"model": "test-model", "input": [{"role": "user", "content": "hello"}], "reasoning": {"effort": "low"}, "tools": [{"type": "function", "name": "compile"}]}
    with proxy() as (port, calls):
        assert request(port, path, body) == (200, b'{"status":"completed"}')
    assert calls == [("/responses", body)]


def test_proxy_preserves_sse_and_upstream_errors():
    chunks = (b"event: response.created\n", b'data: {"id":"r1"}\n\n')
    with proxy(Response(chunks=chunks, content_type="text/event-stream")) as (port, _):
        assert request(port)[1] == b"".join(chunks)
    with proxy(Response(status=429, chunks=(b'{"error":"rate limit"}',))) as (port, _):
        assert request(port) == (429, b'{"error":"rate limit"}')


def test_proxy_preserves_retry_and_request_identity_without_sensitive_headers():
    upstream = Response(status=429)
    upstream.headers.update({"retry-after": "5", "x-request-id": "test-request", "authorization": "sensitive-upstream-token"})
    with proxy(upstream) as (port, _), closing(HTTPConnection("127.0.0.1", port, timeout=5)) as connection:
        connection.request("POST", "/responses", json.dumps({"model": "test-model"}), {"Authorization": "Bearer local-secret"})
        response = connection.getresponse()
        assert response.status == 429
        assert response.getheader("retry-after") == "5"
        assert response.getheader("x-request-id") == "test-request"
        assert response.getheader("authorization") is None
        response.read()


@pytest.mark.parametrize(
    ("path", "body", "key", "status"),
    [
        ("/responses", {"model": "test-model"}, "wrong", 401),
        ("/chat/completions", {"model": "test-model"}, "local-secret", 404),
        ("/responses", {"model": "other-model"}, "local-secret", 400),
        ("/responses", [], "local-secret", 400),
    ],
)
def test_proxy_rejects_unconfigured_requests(path, body, key, status):
    with proxy() as (port, calls):
        assert request(port, path, body, key)[0] == status
    assert calls == []


def test_transport_errors_are_explicit_and_do_not_return_success(caplog):
    with proxy(failure=True) as (port, _):
        status, body = request(port)
    assert status == 502
    assert b"transport failed" in body
    assert "Evaluation inference transport failed" in caplog.text


@pytest.mark.parametrize(("key", "status"), [("local-secret", 200), ("wrong", 401)])
def test_health_requires_authentication_and_reports_real_readiness(key, status):
    with proxy() as (port, calls), closing(HTTPConnection("127.0.0.1", port, timeout=5)) as connection:
        connection.request("GET", "/health", headers={"Authorization": f"Bearer {key}"})
        response = connection.getresponse()
        assert response.status == status
        body = json.loads(response.read())
    assert calls == []
    if status == 200:
        assert body == {"status": "ready", "wireApi": "responses", "model": "test-model"}
        assert "error" not in body


def test_proxy_rejects_malformed_or_oversized_requests():
    with proxy() as (port, calls):
        for body, headers, expected in [
            ("not-json", {}, 400),
            ("{}", {"Content-Length": "not-an-integer"}, 400),
            ("", {"Content-Length": str(16 * 1024 * 1024 + 1)}, 413),
        ]:
            with closing(HTTPConnection("127.0.0.1", port, timeout=5)) as connection:
                connection.request("POST", "/responses", body, {"Authorization": "Bearer local-secret", **headers})
                response = connection.getresponse()
                assert response.status == expected
                response.read()
    assert calls == []
