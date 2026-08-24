import base64
import json
import threading
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from bcbench.agent.shared.mcp_gateway import start_bc_mcp_gateway
from bcbench.exceptions import AgentError


class _UpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # match stdlib signature; silence access log
        pass

    def _record(self) -> None:
        self.server.last_headers = dict(self.headers.items())
        self.server.last_path = self.path
        self.server.last_method = self.command
        length = self.headers.get("Content-Length")
        self.server.last_body = self.rfile.read(int(length)) if length else b""

    def do_POST(self) -> None:
        self._record()
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "sess-123")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        self._record()
        # Stream an SSE response with no Content-Length, ended by closing the connection.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b"event: message\ndata: one\n\n")
        self.wfile.flush()
        self.wfile.write(b"event: message\ndata: two\n\n")
        self.wfile.flush()


@pytest.fixture
def upstream():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
    server.last_headers = {}
    server.last_path = None
    server.last_method = None
    server.last_body = b""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture
def gateway(upstream, monkeypatch):
    port = upstream.server_address[1]
    monkeypatch.setenv("BC_MCP_URL", f"http://127.0.0.1:{port}/BC")
    monkeypatch.setenv("BC_SERVER_USERNAME", "admin")
    monkeypatch.setenv("BC_SERVER_PASSWORD", "secret")
    monkeypatch.setenv("BC_MCP_COMPANY", "CRONUS International Ltd.")
    gw = start_bc_mcp_gateway(enabled=True)
    yield gw
    gw.stop()


def _request(base_url: str, method: str, path: str, body: bytes | None = None):
    split = urlsplit(base_url)
    conn = HTTPConnection(split.hostname, split.port, timeout=10)
    try:
        conn.request(method, path, body=body)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


class TestBcMcpGateway:
    def test_disabled_returns_none(self):
        assert start_bc_mcp_gateway(enabled=False) is None

    def test_raises_without_upstream_url(self, monkeypatch):
        monkeypatch.delenv("BC_MCP_URL", raising=False)
        with pytest.raises(AgentError):
            start_bc_mcp_gateway(enabled=True)

    def test_base_url_mirrors_upstream_path(self, gateway):
        assert gateway.base_url.endswith("/BC")
        assert gateway.base_url.startswith("http://127.0.0.1:")

    def test_forwards_mcp_post_and_injects_credentials(self, gateway, upstream):
        status, _headers, body = _request(gateway.base_url, "POST", "/BC/mcp", body=b'{"jsonrpc":"2.0"}')

        assert status == 200
        assert json.loads(body)["result"] == {"ok": True}
        # The upstream saw the injected credentials/headers, not the (credential-free) agent request.
        expected_auth = "Basic " + base64.b64encode(b"admin:secret").decode()
        assert upstream.last_headers["Authorization"] == expected_auth
        assert upstream.last_headers["ConfigurationName"] == "BCBench"
        assert upstream.last_headers["Company"] == "CRONUS International Ltd."
        assert upstream.last_path == "/BC/mcp"
        assert upstream.last_body == b'{"jsonrpc":"2.0"}'

    def test_passes_through_response_headers(self, gateway):
        _status, headers, _body = _request(gateway.base_url, "POST", "/BC/mcp", body=b"{}")
        assert headers.get("Mcp-Session-Id") == "sess-123"

    def test_streams_sse_response(self, gateway):
        status, headers, body = _request(gateway.base_url, "GET", "/BC/mcp")
        assert status == 200
        assert headers["Content-Type"] == "text/event-stream"
        assert b"data: one" in body
        assert b"data: two" in body

    def test_rejects_non_mcp_path(self, gateway, upstream):
        status, _headers, _body = _request(gateway.base_url, "GET", "/BC/api/v2.0/companies")
        assert status == 403
        # A blocked request never reaches the upstream.
        assert upstream.last_path is None

    def test_rejects_mcp_prefix_without_boundary(self, gateway):
        status, _headers, _body = _request(gateway.base_url, "POST", "/BC/mcpsomething", body=b"{}")
        assert status == 403

    def test_counts_forwarded_requests(self, gateway):
        _request(gateway.base_url, "POST", "/BC/mcp", body=b"{}")
        _request(gateway.base_url, "GET", "/BC/api")  # blocked, not counted
        _request(gateway.base_url, "POST", "/BC/mcp", body=b"{}")
        assert gateway.forwarded_count == 2
