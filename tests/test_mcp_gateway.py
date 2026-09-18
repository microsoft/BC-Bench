import base64
import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from bcbench.agent.shared.managed_clients import ManagedAgentClients
from bcbench.agent.shared.mcp_gateway import BcMcpGateway, start_bc_mcp_gateway
from bcbench.exceptions import AgentError
from bcbench.types import AgentRuntimeConfig, ContainerConfig

_WARMUP_MODULE = "bcbench.agent.shared.mcp_gateway"


@pytest.fixture(autouse=True)
def _fast_warmup(monkeypatch):
    # Keep warm-up single-shot and delay-free so a mock that returns no tools gives up instantly
    # instead of retrying for the real budget. Tests that exercise the retry loop override these.
    monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_BUDGET_SECONDS", 0.0)
    monkeypatch.setattr(f"{_WARMUP_MODULE}._WARMUP_RETRY_DELAY_SECONDS", 0.0)


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


@pytest.fixture
def idle_sse_gateway():
    release = threading.Event()

    class IdleSseHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
            release.wait(timeout=20)
            self.close_connection = True

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.do_GET()

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), IdleSseHandler)
    listener = threading.Thread(target=upstream.serve_forever, daemon=True)
    listener.start()
    gateway = BcMcpGateway(f"http://127.0.0.1:{upstream.server_address[1]}/BC", "admin", "secret", None).start()
    server = gateway._server
    try:
        yield gateway, release
    finally:
        release.set()
        gateway.stop()
        with server.thread_lock:
            clients = tuple(server.active_threads)
        for client in clients:
            client.join(timeout=5)
        upstream.shutdown()
        upstream.server_close()
        listener.join(timeout=5)


@pytest.mark.parametrize("stop_mode", ["legacy", "lifecycle"])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_stop_interrupts_idle_upstream_sse_after_downstream_disconnect(idle_sse_gateway, stop_mode, method):
    gateway, release = idle_sse_gateway
    server, listener = gateway._server, gateway._thread
    split = urlsplit(gateway.base_url)
    connection = HTTPConnection(split.hostname, split.port, timeout=10)
    try:
        body = b'{"jsonrpc":"2.0","id":1,"method":"initialize"}' if method == "POST" else None
        connection.request(method, "/BC/mcp", body=body)
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type") == "text/event-stream"
        with server.thread_lock:
            requests = tuple(server.active_threads)
        assert requests
        assert all(request.is_alive() for request in requests)
        connection.sock.shutdown(socket.SHUT_RDWR)
        response.close()
        connection.close()
        started = time.monotonic()
        if stop_mode == "lifecycle":
            clients = ManagedAgentClients()
            clients.register(gateway.stop_verified)
            clients.stop()
            clients.stop()
        else:
            gateway.stop()
        assert time.monotonic() - started < 3
        assert not release.is_set()
        assert not listener.is_alive()
        assert not any(request.is_alive() for request in requests)
        with pytest.raises(ConnectionError):
            _request(gateway.base_url, "GET", "/BC/mcp")
    finally:
        connection.close()


def test_verified_stop_interrupts_pending_downstream_body_and_rejects_late_acceptance(idle_sse_gateway):
    gateway, _ = idle_sse_gateway
    server = gateway._server
    split = urlsplit(gateway.base_url)
    with socket.create_connection((split.hostname, split.port), timeout=5) as connection:
        connection.sendall(b"POST /BC/mcp HTTP/1.1\r\nHost: localhost\r\nContent-Length: 100\r\n\r\n{")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with server.thread_lock:
                requests = tuple(server.active_threads)
            if requests:
                break
            time.sleep(0.01)
        assert requests
        gateway.stop_verified()
        assert not any(request.is_alive() for request in requests)
        assert gateway.forwarded_count == 0
        with server.thread_lock:
            assert not server.active_connections
            assert not server.active_threads

    accepted, peer = socket.socketpair()
    with accepted, peer:
        server.process_request(accepted, ("127.0.0.1", 1))
        assert accepted.fileno() == -1
        with pytest.raises(ConnectionAbortedError, match="stopping"):
            server.register_connection(peer)
        assert not server.active_connections
        assert not server.active_threads


def test_upstream_connect_racing_shutdown_is_closed_without_forwarding(idle_sse_gateway, monkeypatch):
    gateway, _ = idle_sse_gateway
    server = gateway._server
    connected = threading.Event()
    resume = threading.Event()
    original_connect = HTTPConnection.connect

    def delayed_connect(connection):
        original_connect(connection)
        if connection.port == gateway._origin_port:
            connected.set()
            assert resume.wait(timeout=5)

    monkeypatch.setattr(HTTPConnection, "connect", delayed_connect)
    split = urlsplit(gateway.base_url)
    connection = HTTPConnection(split.hostname, split.port, timeout=5)
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            connection.request("GET", "/BC/mcp")
            assert connected.wait(timeout=2)
            stopped = executor.submit(gateway.stop_verified)
            assert server.stopping.wait(timeout=2)
            resume.set()
            stopped.result(timeout=3)
            assert gateway.forwarded_count == 0
            with server.thread_lock:
                assert not server.active_connections
                assert not server.active_threads
        finally:
            resume.set()
            connection.close()


def test_verified_stop_retains_socket_close_failure_and_attempts_every_connection(idle_sse_gateway, monkeypatch):
    gateway, _ = idle_sse_gateway
    server = gateway._server
    first, second = socket.socketpair()
    failed_descriptor = first.fileno()
    other_descriptor = second.fileno()
    server.register_connection(first)
    server.register_connection(second)
    close = socket.close
    attempts = []

    def fail_one_close(descriptor):
        attempts.append(descriptor)
        if descriptor == failed_descriptor:
            raise OSError("injected socket close failure")
        close(descriptor)

    monkeypatch.setattr(socket, "close", fail_one_close)
    try:
        with pytest.raises(AgentError, match="socket shutdown was not verified") as failure:
            gateway.stop_verified()
        assert {failed_descriptor, other_descriptor} <= set(attempts)
        with pytest.raises(AgentError) as repeated:
            gateway.stop_verified()
        assert repeated.value is failure.value
    finally:
        close(failed_descriptor)
        first.close()
        second.close()


class TestBcMcpGateway:
    def test_verified_stop_rejects_a_still_active_client(self, gateway):
        from unittest.mock import Mock

        client = Mock()
        client.is_alive.return_value = True
        server = gateway._server
        with server.thread_lock:
            server.active_threads.add(client)
        with pytest.raises(AgentError, match="active client") as failure:
            gateway.stop_verified()
        client.join.assert_called_once()
        client.is_alive.return_value = False
        with pytest.raises(AgentError) as repeated:
            gateway.stop_verified()
        assert repeated.value is failure.value

    def test_verified_stop_closes_listener(self, gateway):
        url = gateway.base_url
        gateway.stop_verified()
        with pytest.raises(ConnectionError):
            _request(url, "GET", "/BC/mcp")

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
    def mcp_gateway(self):
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
