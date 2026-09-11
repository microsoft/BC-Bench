import base64
import io
import json
import logging
import threading
import time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, Mock
from urllib.parse import urlsplit

import pytest

from bcbench.agent.shared.mcp_gateway import BcMcpGateway, _build_handler, start_bc_mcp_gateway
from bcbench.types import AgentRuntimeConfig, ContainerConfig

_WARMUP_MODULE = "bcbench.agent.shared.mcp_gateway"


@pytest.fixture(autouse=True)
def _fast_warmup(monkeypatch):
    # Ordinary proxy tests skip warm-up; probe tests opt into a positive budget.
    monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_BUDGET_SECONDS", 0.0)
    monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_RETRY_DELAY_SECONDS", 0.0)


@pytest.fixture(autouse=True)
def _gateway_logging(monkeypatch, caplog):
    # Other tests configure console handlers tied to their own (subsequently closed) capture streams.
    logger = logging.getLogger(_WARMUP_MODULE)
    monkeypatch.setattr(logger, "handlers", [caplog.handler])
    monkeypatch.setattr(logger, "propagate", False)


class _RecordingServer(ThreadingHTTPServer):
    last_headers: dict[str, str] = {}  # noqa: RUF012 - reassigned per instance by the fixture
    last_path: str | None = None
    last_method: str | None = None
    last_body: bytes = b""


class _UpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # match stdlib signature; silence access log
        pass

    def _record(self) -> None:
        assert isinstance(self.server, _RecordingServer)
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
    server = _RecordingServer(("127.0.0.1", 0), _UpstreamHandler)
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
def gateway(upstream):
    port = upstream.server_address[1]
    container = ContainerConfig(
        "bcbench",
        "admin",
        "secret",
        mcp_url=f"http://127.0.0.1:{port}/BC",
        company="CRONUS International Ltd.",
    )
    gw = start_bc_mcp_gateway(AgentRuntimeConfig(container=container, bc_mcp=True))
    assert gw is not None
    yield gw
    gw.stop()


def _request(base_url: str, method: str, path: str, body: bytes | None = None):
    split = urlsplit(base_url)
    conn = HTTPConnection(split.hostname or "127.0.0.1", split.port, timeout=10)
    try:
        conn.request(method, path, body=body)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


class TestBcMcpGateway:
    def test_disabled_returns_none(self):
        assert start_bc_mcp_gateway(None) is None

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
        upstream.last_path = None  # clear traffic from the start-up warm-up probe
        status, _headers, _body = _request(gateway.base_url, "GET", "/BC/api/v2.0/companies")
        assert status == 403
        # A blocked request never reaches the upstream.
        assert upstream.last_path is None

    def test_rejects_mcp_prefix_without_boundary(self, gateway):
        status, _headers, _body = _request(gateway.base_url, "POST", "/BC/mcpsomething", body=b"{}")
        assert status == 403

    def test_counts_forwarded_requests(self, gateway):
        baseline = gateway.forwarded_count  # start_bc_mcp_gateway already ran a warm-up probe
        _request(gateway.base_url, "POST", "/BC/mcp", body=b"{}")
        _request(gateway.base_url, "GET", "/BC/api")  # blocked, not counted
        _request(gateway.base_url, "POST", "/BC/mcp", body=b"{}")
        assert gateway.forwarded_count - baseline == 2


class _McpHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # match stdlib signature; silence access log
        pass

    def do_POST(self) -> None:
        import json as _json

        n = int(self.headers.get("Content-Length", 0))
        req = _json.loads(self.rfile.read(n)) if n else {}
        method = req.get("method")
        if method == "initialize":
            self._json({"jsonrpc": "2.0", "id": req.get("id"), "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}}, {"Mcp-Session-Id": "sess-xyz"})
        elif method and method.startswith("notifications/"):
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif method == "tools/list":
            tools = [{"name": "bc_data_find_tables"}, {"name": "bc_data_query"}]
            # Answer as SSE to exercise the gateway's chunked relay + the probe's SSE parsing.
            payload = "event: message\ndata: " + _json.dumps({"jsonrpc": "2.0", "id": req.get("id"), "result": {"tools": tools}}) + "\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload.encode())
        else:
            self._json({"jsonrpc": "2.0", "id": req.get("id"), "result": {}})

    def _json(self, obj, extra_headers=None) -> None:
        import json as _json

        body = _json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestBcMcpProbe:
    @pytest.fixture
    def mcp_gateway(self, monkeypatch):
        monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_BUDGET_SECONDS", 5.0)
        server = ThreadingHTTPServer(("127.0.0.1", 0), _McpHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        container = ContainerConfig("bcbench", "admin", "secret", "CRONUS", mcp_url=f"http://127.0.0.1:{port}/BC")
        gw = start_bc_mcp_gateway(AgentRuntimeConfig(container=container, bc_mcp=True))
        assert gw is not None
        yield gw
        gw.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    def test_warm_up_returns_exposed_tool_names(self, mcp_gateway):
        assert mcp_gateway.warm_up() == ["bc_data_find_tables", "bc_data_query"]

    def test_tools_list_served_from_cache_after_warmup(self, mcp_gateway):
        # start_bc_mcp_gateway already ran warm-up, populating the tools/list cache.
        import json as _json

        assert mcp_gateway.base_url is not None
        status, headers, body = _request(mcp_gateway.base_url, "POST", "/BC/mcp", body=b'{"jsonrpc":"2.0","id":7,"method":"tools/list"}')
        assert status == 200
        # Served as a single-event SSE stream, mirroring BC's tools/list framing.
        assert headers["Content-Type"] == "text/event-stream"
        data_line = next(line for line in body.decode().splitlines() if line.startswith("data:"))
        payload = _json.loads(data_line[len("data:") :].strip())
        assert payload["id"] == 7
        assert [t["name"] for t in payload["result"]["tools"]] == ["bc_data_find_tables", "bc_data_query"]

    def test_warm_up_never_raises_on_bad_upstream(self, monkeypatch):
        monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_BUDGET_SECONDS", 0.05)
        monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_RETRY_DELAY_SECONDS", 0.05)
        container = ContainerConfig("bcbench", "admin", "secret", "CRONUS", mcp_url="http://127.0.0.1:1/BC")
        gw = start_bc_mcp_gateway(AgentRuntimeConfig(container=container, bc_mcp=True))
        assert gw is not None
        try:
            assert gw.warm_up() == []
        finally:
            gw.stop()


class _EmptyThenToolsHandler(BaseHTTPRequestHandler):
    """Returns an empty tools/list on the first call, then the real tools - to exercise warm-up retries."""

    protocol_version = "HTTP/1.1"
    tools_list_calls = 0

    def log_message(self, format: str, *args: object) -> None:  # match stdlib signature; silence access log
        pass

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n)) if n else {}
        method = req.get("method")
        if method == "initialize":
            self._json({"jsonrpc": "2.0", "id": req.get("id"), "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}}, {"Mcp-Session-Id": "s"})
        elif method and method.startswith("notifications/"):
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif method == "tools/list":
            type(self).tools_list_calls += 1
            tools = [] if type(self).tools_list_calls < 2 else [{"name": "bc_data_query"}]
            self._json({"jsonrpc": "2.0", "id": req.get("id"), "result": {"tools": tools}})
        else:
            self._json({"jsonrpc": "2.0", "id": req.get("id"), "result": {}})

    def _json(self, obj, extra=None) -> None:
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_warm_up_retries_until_tools_available(monkeypatch):
    monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_BUDGET_SECONDS", 30.0)
    monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_RETRY_DELAY_SECONDS", 0.0)
    _EmptyThenToolsHandler.tools_list_calls = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EmptyThenToolsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    gateway = BcMcpGateway(f"http://127.0.0.1:{port}/BC", "admin", "secret", None).start()
    try:
        assert gateway.warm_up() == ["bc_data_query"]
        assert _EmptyThenToolsHandler.tools_list_calls >= 2  # retried past the first empty result
    finally:
        gateway.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _HeldOpenSseHandler(BaseHTTPRequestHandler):
    """Sends one small SSE event, flushes, then holds the stream open before closing."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # match stdlib signature; silence access log
        pass

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b"event: message\ndata: early\n\n")
        self.wfile.flush()
        time.sleep(3.0)  # keep the stream open after the event, as the BC MCP endpoint does


class _HeldOpenPostSseHandler(BaseHTTPRequestHandler):
    """Answers a POST with an SSE event carrying a JSON-RPC result, then holds the stream open."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # match stdlib signature; silence access log
        pass

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length", 0))
        if n:
            self.rfile.read(n)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Mcp-Session-Id", "sess-hold")
        self.end_headers()
        self.wfile.write(b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n')
        self.wfile.flush()
        time.sleep(30)  # hold open like BC; the gateway relays faithfully without waiting for the end


def test_gateway_relays_post_sse_event_promptly_without_waiting_for_close():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HeldOpenPostSseHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    gateway = BcMcpGateway(f"http://127.0.0.1:{port}/BC", "admin", "secret", None).start()
    split = urlsplit(gateway.base_url or "")
    connection = HTTPConnection(split.hostname or "127.0.0.1", split.port, timeout=10)
    try:
        start = time.monotonic()
        connection.request("POST", "/BC/mcp", body=b'{"jsonrpc":"2.0","id":1,"method":"initialize"}')
        response = connection.getresponse()
        # The gateway relays BC's SSE bytes faithfully (holding the stream open); the response event
        # reaches the client promptly even though the upstream keeps the stream open.
        assert response.status == 200
        assert response.getheader("Content-Type") == "text/event-stream"
        line = b""
        while b"data:" not in line:
            line = response.readline()
            if not line:
                break
        elapsed = time.monotonic() - start
        assert b'"result"' in line
        assert elapsed < 3.0
    finally:
        connection.close()
        gateway.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _InitializeExperimentalHandler(BaseHTTPRequestHandler):
    """Answers initialize over SSE with a capabilities.experimental block, held open like BC."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # match stdlib signature; silence access log
        pass

    def do_POST(self) -> None:
        import json as _json

        n = int(self.headers.get("Content-Length", 0))
        req = _json.loads(self.rfile.read(n)) if n else {}
        result = {"protocolVersion": "2024-11-05", "capabilities": {"experimental": {"x-ms-headerless": True}, "tools": {}}, "serverInfo": {"name": "BC"}}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Mcp-Session-Id", "sess-init")
        self.end_headers()
        self.wfile.write(("data: " + _json.dumps({"jsonrpc": "2.0", "id": req.get("id"), "result": result}) + "\n\n").encode())
        self.wfile.flush()
        time.sleep(30)  # hold the stream open like BC


def test_gateway_strips_experimental_from_initialize():
    import json as _json

    server = ThreadingHTTPServer(("127.0.0.1", 0), _InitializeExperimentalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    gateway = BcMcpGateway(f"http://127.0.0.1:{port}/BC", "admin", "secret", None).start()
    split = urlsplit(gateway.base_url or "")
    connection = HTTPConnection(split.hostname or "127.0.0.1", split.port, timeout=10)
    try:
        connection.request("POST", "/BC/mcp", body=b'{"jsonrpc":"2.0","id":1,"method":"initialize"}')
        response = connection.getresponse()
        assert response.status == 200
        line = b""
        while b"data:" not in line:
            line = response.readline()
            if not line:
                break
        payload = _json.loads(line.decode()[len("data:") :].strip())
        # The x-ms-headerless experimental capability (which breaks Claude) is stripped; the rest stays.
        assert "experimental" not in payload["result"]["capabilities"]
        assert "tools" in payload["result"]["capabilities"]
        assert payload["result"]["protocolVersion"] == "2024-11-05"
    finally:
        connection.close()
        gateway.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_gateway_relays_held_open_sse_event_promptly():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HeldOpenSseHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    gateway = BcMcpGateway(f"http://127.0.0.1:{port}/BC", "admin", "secret", None).start()
    split = urlsplit(gateway.base_url or "")
    connection = HTTPConnection(split.hostname or "127.0.0.1", split.port, timeout=10)
    try:
        connection.request("GET", "/BC/mcp")
        response = connection.getresponse()
        start = time.monotonic()
        line = b""
        while b"data:" not in line:
            line = response.readline()
            if not line:
                break
        elapsed = time.monotonic() - start
        assert b"data: early" in line
        # read1() flushes the event immediately; the old read() would stall until the upstream closes (~3s).
        assert elapsed < 2.0
    finally:
        connection.close()
        gateway.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_warm_up_zero_budget_does_not_attempt_handshake(monkeypatch, caplog):
    gateway = BcMcpGateway("http://localhost/BC", "admin", "secret", None)
    handshake = Mock()
    monkeypatch.setattr(gateway, "_handshake_tools", handshake)
    assert gateway.warm_up() == []
    handshake.assert_not_called()
    assert "0 attempt(s)" in caplog.text


def test_warm_up_recovers_from_timeout_without_warning(monkeypatch, caplog):
    monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_BUDGET_SECONDS", 5.0)
    gateway = BcMcpGateway("http://localhost/BC", "admin", "secret", None)
    connection = MagicMock()
    response = connection.getresponse.return_value.__enter__.return_value
    response.getheader.side_effect = lambda name, default=None: "session" if name == "Mcp-Session-Id" else "application/json"
    response.read.side_effect = [b"{}", b"", TimeoutError("timed out"), b"{}", b"", b'{"result":{"tools":[{"name":"bc_data_query"}]}}']
    probe = MagicMock()
    probe.return_value.__enter__.return_value = connection
    monkeypatch.setattr(f"{_WARMUP_MODULE}._probe_connection", probe)
    with caplog.at_level(logging.INFO, logger=_WARMUP_MODULE):
        assert gateway.warm_up() == ["bc_data_query"]
    assert all(record.levelno < logging.WARNING for record in caplog.records)
    assert "tools/list failed after" in caplog.text
    assert "TimeoutError: timed out" in caplog.text
    assert "retrying in" in caplog.text
    assert gateway._cached_tools_result == {"tools": [{"name": "bc_data_query"}]}


def test_warm_up_bounds_attempt_deadlines_and_retry_sleep(monkeypatch, caplog):
    now = [100.0]
    monkeypatch.setattr(f"{_WARMUP_MODULE}.time.monotonic", lambda: now[0])
    monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_BUDGET_SECONDS", 3.0)
    monkeypatch.setattr(f"{_WARMUP_MODULE}._PROBE_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_RETRY_DELAY_SECONDS", 0.75)
    deadlines = []
    sleeps = []

    def handshake(deadline):
        deadlines.append(deadline)
        now[0] = deadline
        raise TimeoutError("tools/list stalled")

    def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    gateway = BcMcpGateway("http://localhost/BC", "admin", "secret", None)
    monkeypatch.setattr(gateway, "_handshake_tools", handshake)
    monkeypatch.setattr(f"{_WARMUP_MODULE}.time.sleep", sleep)
    with caplog.at_level(logging.INFO, logger=_WARMUP_MODULE):
        assert gateway.warm_up() == []
    assert deadlines == [101.0, 102.75]
    assert sleeps == [0.75, 0.25]
    assert now[0] == 103.0
    warnings = [record.message for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "gave up after 2 attempt(s) and 3.0s" in warnings[0]
    assert "tools/list stalled" in warnings[0]


def test_handshake_shares_one_deadline_across_rpcs(monkeypatch):
    gateway = BcMcpGateway("http://localhost/BC", "admin", "secret", None)
    rpc = Mock(side_effect=[("session", {}), (None, {}), (None, {"result": {"tools": [{"name": "query"}]}})])
    monkeypatch.setattr(gateway, "_rpc", rpc)
    assert gateway._handshake_tools(123.0) == ["query"]
    assert [call.args[3] for call in rpc.call_args_list] == ["initialize", "notifications/initialized", "tools/list"]
    assert [call.kwargs["deadline"] for call in rpc.call_args_list] == [123.0] * 3


def test_warm_up_unexpected_errors_remain_visible(monkeypatch, caplog):
    monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_BUDGET_SECONDS", 0.01)
    monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_RETRY_DELAY_SECONDS", 1.0)
    gateway = BcMcpGateway("http://localhost/BC", "admin", "secret", None)
    monkeypatch.setattr(gateway, "_handshake_tools", Mock(side_effect=ValueError("unexpected bug")))
    assert gateway.warm_up() == []
    assert any(record.levelno == logging.ERROR and record.exc_info for record in caplog.records)
    assert "unexpected bug" in caplog.text


@pytest.mark.parametrize("phase", ["headers", "json", "sse"])
@pytest.mark.parametrize("trickle", [False, True])
def test_warm_up_deadline_interrupts_blocking_io(monkeypatch, caplog, phase, trickle):
    finished = threading.Event()
    release = threading.Event()

    class Handler(_McpHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            try:
                if phase == "headers":
                    self.connection.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json" if phase == "json" else "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(b"{" if phase == "json" else b"data: {")
                if trickle:
                    while not release.wait(0.01):
                        self.connection.sendall(b" ")
                else:
                    assert self.connection.recv(1) == b""
            except (ConnectionResetError, BrokenPipeError):
                pass
            finally:
                self.close_connection = True
                finished.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_BUDGET_SECONDS", 0.15)
    monkeypatch.setattr(f"{_WARMUP_MODULE}._PROBE_TIMEOUT_SECONDS", 5.0)
    gateway = BcMcpGateway(f"http://127.0.0.1:{server.server_address[1]}/BC", "admin", "secret", None)
    try:
        started = time.monotonic()
        assert gateway.warm_up() == []
        assert time.monotonic() - started < 1.0
        assert finished.wait(1.0), "probe socket was not shut down"
        assert "initialize failed after" in caplog.text
        assert "TimeoutError" in caplog.text
        assert len([record for record in caplog.records if record.levelno >= logging.WARNING]) == 1
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("content_type", ["application/json", "text/event-stream"])
def test_probe_closes_held_open_response_after_result(content_type):
    finished = threading.Event()

    class Handler(_McpHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            payload = b'{"result":{"tools":[{"name":"query"}]}}'
            if content_type == "text/event-stream":
                payload = b"data: " + payload + b"\n\n"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            if content_type == "application/json":
                self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()
            assert self.connection.recv(1) == b""
            self.close_connection = True
            finished.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    gateway = BcMcpGateway(f"http://127.0.0.1:{port}/BC", "admin", "secret", None)
    try:
        started = time.monotonic()
        _, result = gateway._rpc("127.0.0.1", port, {}, "tools/list", {}, deadline=started + 2.0)
        assert result == {"result": {"tools": [{"name": "query"}]}}
        assert time.monotonic() - started < 1.0
        assert finished.wait(1.0)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _client_request(body=b"{}", path="/BC/mcp"):
    return f"POST {path} HTTP/1.1\r\nHost: localhost\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body


@pytest.mark.parametrize("error_type", [ConnectionResetError, BrokenPipeError])
@pytest.mark.parametrize("phase", ["request_line", "body", "idle_keepalive", "cached_headers", "cached_body", "error_headers", "error_body", "flush", "finish"])
def test_downstream_disconnects_are_debug_only(monkeypatch, caplog, capsys, error_type, phase):
    gateway = BcMcpGateway("http://localhost/BC", "admin", "secret", None)
    gateway._cached_tools_result = {"tools": [{"name": "query"}]}
    body = b'{"method":"tools/list","id":1}'
    request = Mock()
    stream = io.BytesIO(_client_request(body, "/forbidden" if phase.startswith("error") else "/BC/mcp"))
    request.makefile.return_value = stream
    error = error_type("client left")
    if phase in ("request_line", "body"):
        request.makefile.return_value = Mock(wraps=stream)
        getattr(request.makefile.return_value, "readline" if phase == "request_line" else "read").side_effect = error
    elif phase == "idle_keepalive":
        request.makefile.return_value = Mock(wraps=stream)

        def readline(limit):
            line = stream.readline(limit)
            if not line:
                raise error
            return line

        request.makefile.return_value.readline.side_effect = readline
    elif phase.endswith("headers"):
        request.sendall.side_effect = error
    elif phase.endswith("body"):
        request.sendall.side_effect = [None, error]
    handler_type = _build_handler(gateway)
    if phase == "flush":
        setup = handler_type.setup

        def failing_flush_setup(self):
            setup(self)
            self.wfile.flush = Mock(side_effect=error)

        monkeypatch.setattr(handler_type, "setup", failing_flush_setup)
    if phase == "finish":
        finish = handler_type.finish

        def failing_finish(self):
            finish(self)
            raise error

        monkeypatch.setattr(handler_type, "finish", failing_finish)
    upstream_connection = Mock()
    monkeypatch.setattr(f"{_WARMUP_MODULE}.HTTPConnection", upstream_connection)
    with caplog.at_level(logging.DEBUG, logger=_WARMUP_MODULE):
        handler = handler_type(request, ("127.0.0.1", 1), Mock())
    assert handler.close_connection
    upstream_connection.assert_not_called()
    assert request.sendall.call_count == (0 if phase in ("request_line", "body") else 1 if phase.endswith("headers") else 2)
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.DEBUG
    assert caplog.records[0].exc_info is None
    assert "client disconnected" in caplog.text
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("error_type", [ConnectionResetError, TimeoutError])
@pytest.mark.parametrize("phase", ["request", "headers", "body", "stream", "initialize"])
def test_upstream_failures_remain_visible_and_do_not_send_second_response(monkeypatch, caplog, error_type, phase):
    gateway = BcMcpGateway("http://localhost/BC", "admin", "secret", None)
    request = Mock()
    body = b'{"method":"initialize"}' if phase == "initialize" else b"{}"
    request.makefile.return_value = io.BytesIO(_client_request(body))
    connection = MagicMock()
    response = connection.getresponse.return_value
    response.__enter__.return_value = response
    response.status = 200
    response.getheader.return_value = "text/event-stream"
    response.getheaders.return_value = [("Content-Length", "10")] if phase == "body" else []
    error = error_type("upstream failed")
    if phase == "request":
        connection.request.side_effect = error
    elif phase == "headers":
        connection.getresponse.side_effect = error
    else:
        getattr(response, {"body": "read", "stream": "read1", "initialize": "readline"}[phase]).side_effect = error
    monkeypatch.setattr(f"{_WARMUP_MODULE}.HTTPConnection", Mock(return_value=connection))
    handler = _build_handler(gateway)(request, ("127.0.0.1", 1), Mock())
    assert handler.close_connection
    connection.close.assert_called_once()
    if phase not in ("request", "headers"):
        response.__exit__.assert_called_once()
    output = b"".join(call.args[0] for call in request.sendall.call_args_list)
    assert output.count(b"HTTP/1.1") == 1
    assert (b"502" in output) == (phase in ("request", "headers"))
    assert b"0\r\n\r\n" not in output.split(b"\r\n\r\n", 1)[1]
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.ERROR
    assert caplog.records[0].exc_info
    assert "upstream failure" in caplog.text
    assert "client disconnected" not in caplog.text


def test_unexpected_proxy_bug_is_not_suppressed(monkeypatch):
    gateway = BcMcpGateway("http://localhost/BC", "admin", "secret", None)
    request = Mock()
    request.makefile.return_value = io.BytesIO(_client_request())
    connection = Mock()
    connection.request.side_effect = ValueError("unexpected bug")
    monkeypatch.setattr(f"{_WARMUP_MODULE}.HTTPConnection", Mock(return_value=connection))
    with pytest.raises(ValueError, match="unexpected bug"):
        _build_handler(gateway)(request, ("127.0.0.1", 1), Mock())
    connection.close.assert_called_once()


@pytest.mark.parametrize("error_type", [ConnectionResetError, BrokenPipeError])
@pytest.mark.parametrize("initialize", [False, True])
def test_downstream_disconnect_during_relay_is_not_an_upstream_error(monkeypatch, caplog, error_type, initialize):
    gateway = BcMcpGateway("http://localhost/BC", "admin", "secret", None)
    request = Mock()
    request.makefile.return_value = io.BytesIO(_client_request(b'{"method":"initialize"}' if initialize else b"{}"))
    request.sendall.side_effect = [None, error_type("client left")]
    connection = MagicMock()
    response = connection.getresponse.return_value
    response.__enter__.return_value = response
    response.status = 200
    response.getheader.return_value = "text/event-stream"
    response.getheaders.return_value = []
    response.read1.return_value = b"data: {}\n\n"
    response.readline.return_value = b"data: {}\n"
    monkeypatch.setattr(f"{_WARMUP_MODULE}.HTTPConnection", Mock(return_value=connection))
    with caplog.at_level(logging.DEBUG, logger=_WARMUP_MODULE):
        handler = _build_handler(gateway)(request, ("127.0.0.1", 1), Mock())
    assert handler.close_connection
    assert request.sendall.call_count == 2
    connection.close.assert_called_once()
    response.__exit__.assert_called_once()
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.DEBUG
    assert caplog.records[0].exc_info is None


def test_truncated_upstream_body_closes_downstream(monkeypatch, caplog):
    gateway = BcMcpGateway("http://localhost/BC", "admin", "secret", None)
    request = Mock()
    request.makefile.return_value = io.BytesIO(_client_request())
    connection = MagicMock()
    response = connection.getresponse.return_value
    response.__enter__.return_value = response
    response.status = 200
    response.getheaders.return_value = [("Content-Length", "10")]
    response.read.side_effect = [b"part", b""]
    monkeypatch.setattr(f"{_WARMUP_MODULE}.HTTPConnection", Mock(return_value=connection))
    handler = _build_handler(gateway)(request, ("127.0.0.1", 1), Mock())
    assert handler.close_connection
    output = b"".join(call.args[0] for call in request.sendall.call_args_list)
    assert output == b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\npart"
    assert "IncompleteRead" in caplog.text
    connection.close.assert_called_once()
