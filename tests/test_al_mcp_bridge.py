import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import urlsplit

import anyio
import pytest
import requests
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.types import JSONRPCMessage
from starlette.requests import Request

from bcbench.agent.shared.al_mcp_bridge import AlMcpBridge, AlMcpBridgeError
from bcbench.agent.shared.al_mcp_bridge_worker import _EVENT_BUFFER_SIZE, _BridgeTransport
from bcbench.agent.shared.contained_process import ContainedProcessInfrastructureError, ContainedProcessResult
from bcbench.agent.shared.managed_clients import ManagedAgentClients
from tests.test_contained_process import _pid_is_running

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects are required")
_SERVER = Path(__file__).parent / "fixtures" / "stdio_mcp_server.py"
_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def bridge(tmp_path, request):
    server = {"command": sys.executable, "args": [str(_SERVER)], "env": {"BC_SERVER_PASSWORD": "bridge-only-bc-secret", **getattr(request, "param", {})}}
    instance = AlMcpBridge(server, tmp_path, timeout_seconds=60)
    instance.start()
    try:
        yield instance
    finally:
        instance.stop()


def _rpc(bridge, method, request_id=1, params=None, *, headers=None):
    payload = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        payload["id"] = request_id
    if params is not None:
        payload["params"] = params
    return requests.post(bridge.url, headers={**_HEADERS, **(headers or {})}, json=payload, timeout=10)


def _message(response):
    response.raise_for_status()
    return next(json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:"))


def _initialize(bridge):
    response = _rpc(bridge, "initialize", params={"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
    assert _message(response)["result"]["serverInfo"]["name"] == "fixture"
    headers = {"Mcp-Session-Id": response.headers["Mcp-Session-Id"], "MCP-Protocol-Version": "2025-03-26"}
    assert _rpc(bridge, "notifications/initialized", None, headers=headers).status_code == 202
    return headers


def test_readiness_payload_is_not_consumed_until_publisher_closes_and_signals(tmp_path, monkeypatch):
    published = threading.Event()
    release = threading.Event()
    expected_url = "http://127.0.0.1:12345/token/mcp"

    def publisher(request):
        root = Path(request.command[-1]).parent
        (root / "ready.json").write_text(json.dumps({"url": expected_url}))
        published.set()
        assert release.wait(timeout=5)
        (root / "ready").touch()
        deadline = time.monotonic() + 5
        while not (root / "shutdown").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        return ContainedProcessResult(0, "", "")

    monkeypatch.setattr("bcbench.agent.shared.al_mcp_bridge.run_contained_process", publisher)
    bridge = AlMcpBridge({"command": sys.executable}, tmp_path, timeout_seconds=30)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(bridge.start)
        try:
            assert published.wait(timeout=5)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.2)
            release.set()
            assert future.result(timeout=5).url == expected_url
        finally:
            release.set()
            bridge.stop()


def test_startup_containment_failure_remains_failed_on_every_shutdown(tmp_path, monkeypatch):
    def fail_containment(request):
        raise ContainedProcessInfrastructureError(30, child_stdout="", child_stderr="", wrapper_stdout="", wrapper_stderr="")

    monkeypatch.setattr("bcbench.agent.shared.al_mcp_bridge.run_contained_process", fail_containment)
    clients = ManagedAgentClients()
    with pytest.raises(AlMcpBridgeError, match="containment") as startup_failure:
        clients.start_al_mcp({"command": sys.executable}, tmp_path)
    for _ in range(2):
        with pytest.raises(AlMcpBridgeError) as shutdown_failure:
            clients._stoppers[0]()
        assert shutdown_failure.value is startup_failure.value
        with pytest.raises(RuntimeError, match="shutdown/transport verification failed"):
            clients.stop()


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt("shutdown interrupted"), SystemExit(130)])
def test_managed_client_shutdown_interrupt_is_preserved_and_repeated_stop_fails(interrupt):
    clients = ManagedAgentClients()
    stoppers = [
        Mock(),
        Mock(side_effect=KeyboardInterrupt("later interrupt")),
        Mock(side_effect=ValueError("private client diagnostic")),
        Mock(side_effect=interrupt),
        Mock(side_effect=RuntimeError("private client diagnostic")),
        Mock(),
    ]
    for stop in stoppers:
        clients.register(stop)

    with pytest.raises(type(interrupt)) as initial_failure:
        clients.stop()
    assert initial_failure.value is interrupt
    assert any("shutdown/transport verification failed" in note for note in interrupt.__notes__)
    failures = []
    for _ in range(2):
        with pytest.raises(RuntimeError, match="shutdown/transport verification failed") as failure:
            clients.stop()
        failures.append(failure.value)
        assert failure.value.__cause__ is interrupt
        assert type(interrupt).__name__ in str(failure.value)
        assert "ValueError" in str(failure.value)
        assert "RuntimeError" in str(failure.value)
        assert "private client diagnostic" not in str(failure.value)
    assert failures[0] is failures[1]
    for stop in stoppers:
        stop.assert_called_once()


def test_bridge_forwards_initialization_discovery_calls_and_errors(bridge):
    headers = _initialize(bridge)
    assert _message(_rpc(bridge, "tools/list", 2, headers=headers))["result"]["tools"][0]["name"] == "echo"
    params = {"name": "echo", "arguments": {"value": "actual request"}}
    result = _message(_rpc(bridge, "tools/call", "string-id", params, headers=headers))
    assert result["id"] == "string-id"
    assert json.loads(result["result"]["content"][0]["text"]) == params
    error = _message(_rpc(bridge, "fixture/error", 4, headers=headers))
    assert error["error"] == {"code": -32001, "message": "upstream failure", "data": {"detail": 42}}
    assert _message(_rpc(bridge, "fixture/secret-ready", 5, headers=headers))["result"] == {"configured": True}


@pytest.mark.parametrize("bridge", [{"FIXTURE_INITIALIZE_EVENTS": "1"}], indirect=True)
def test_initialization_notifications_do_not_block_response_before_get(bridge):
    response = _rpc(bridge, "initialize", params={"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
    response.raise_for_status()
    messages = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]
    assert messages == [
        {"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info", "data": "starting"}},
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture", "version": "1"}}},
    ]


@pytest.mark.parametrize("bridge", [{"FIXTURE_INITIALIZE_REQUEST": "1"}], indirect=True)
def test_initialization_server_request_and_client_reply_without_get(bridge, tmp_path):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}
    with requests.post(bridge.url, headers=_HEADERS, json=payload, stream=True, timeout=10) as stream:
        stream.raise_for_status()
        events = (json.loads(line[5:]) for line in stream.iter_lines() if line.startswith(b"data:"))
        assert next(events) == {"jsonrpc": "2.0", "id": "initialize-ping", "method": "ping"}
        headers = {**_HEADERS, "Mcp-Session-Id": stream.headers["Mcp-Session-Id"], "MCP-Protocol-Version": "2025-03-26"}
        reply = {"jsonrpc": "2.0", "id": "initialize-ping", "result": {}}
        assert requests.post(bridge.url, headers=headers, json=reply, timeout=5).status_code == 202
        assert next(events)["result"]["serverInfo"]["name"] == "fixture"
        assert json.loads((tmp_path / "initialize-response.json").read_text()) == reply


@pytest.mark.parametrize("bridge", [{"FIXTURE_INITIALIZE_EVENTS": "1", "FIXTURE_INITIALIZE_REQUEST": "1"}], indirect=True)
def test_sdk_client_initializes_with_notifications_and_server_request_then_discovers_tools(bridge):
    async def check():
        with anyio.fail_after(10):
            async with streamable_http_client(bridge.url) as (read, write, _session_id), ClientSession(read, write) as session:
                assert (await session.initialize()).serverInfo.name == "fixture"
                assert (await session.list_tools()).tools[0].name == "echo"
                result = await session.call_tool("echo", {"value": "sdk request"})
                assert not result.isError

    anyio.run(check)


def test_events_buffer_before_first_get_and_across_reconnection(bridge):
    headers = _initialize(bridge)
    assert _message(_rpc(bridge, "fixture/events", 8, headers=headers))["result"] == {}
    with requests.get(bridge.url, headers={**_HEADERS, **headers}, stream=True, timeout=5) as stream:
        stream.raise_for_status()
        events = (json.loads(line[5:]) for line in stream.iter_lines() if line.startswith(b"data:"))
        assert next(events)["method"] == "notifications/tools/list_changed"
        assert next(events)["method"] == "roots/list"
    time.sleep(0.1)
    assert _message(_rpc(bridge, "fixture/events", 9, headers=headers))["result"] == {}
    with requests.get(bridge.url, headers={**_HEADERS, **headers}, stream=True, timeout=5) as stream:
        stream.raise_for_status()
        events = (json.loads(line[5:]) for line in stream.iter_lines() if line.startswith(b"data:"))
        assert next(events)["method"] == "notifications/tools/list_changed"
        assert next(events)["method"] == "roots/list"
    assert _message(_rpc(bridge, "tools/list", 10, headers=headers))["result"]["tools"][0]["name"] == "echo"


def test_get_reconnection_replays_after_last_received_event_without_loss(bridge):
    headers = {**_HEADERS, **_initialize(bridge)}
    assert _message(_rpc(bridge, "fixture/events", 8, headers=headers))["result"] == {}
    with requests.get(bridge.url, headers=headers, stream=True, timeout=5) as stream:
        stream.raise_for_status()
        event_id = None
        lines = stream.iter_lines()
        for line in lines:
            if line.startswith(b"id:"):
                event_id = line[3:].strip().decode()
            if line.startswith(b"data:"):
                assert json.loads(line[5:])["method"] == "notifications/tools/list_changed"
                break
        assert event_id is not None
        assert requests.get(bridge.url, headers=headers, timeout=5).status_code == 409
    time.sleep(0.1)
    assert _message(_rpc(bridge, "fixture/events", 9, headers=headers))["result"] == {}
    assert requests.get(bridge.url, headers={**headers, "Mcp-Session-Id": "invalid"}, timeout=5).status_code == 404
    assert requests.get(bridge.url, headers={**headers, "Last-Event-ID": "invalid"}, timeout=5).status_code == 400
    assert requests.get(bridge.url, headers={**headers, "Last-Event-ID": "10000"}, timeout=5).status_code == 409
    with requests.get(bridge.url, headers={**headers, "Last-Event-ID": event_id}, stream=True, timeout=5) as stream:
        stream.raise_for_status()
        events = (json.loads(line[5:]) for line in stream.iter_lines() if line.startswith(b"data:"))
        assert [next(events)["method"] for _ in range(3)] == ["roots/list", "notifications/tools/list_changed", "roots/list"]


def test_server_event_buffer_is_bounded_and_undelivered_events_expire():
    async def check():
        transport = _BridgeTransport("session", timeout=1)
        message = JSONRPCMessage.model_validate({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        for _ in range(_EVENT_BUFFER_SIZE):
            transport.buffer_event(message)
        with pytest.raises(BufferError, match="undelivered event buffer exhausted"):
            transport.buffer_event(message)
        assert len(transport._events) == _EVENT_BUFFER_SIZE
        with anyio.fail_after(2), pytest.raises(TimeoutError, match="event delivery timed out"):
            await transport.watch_event_deadlines()

    anyio.run(check)


def test_replay_history_expiring_during_connection_fails_instead_of_skipping_events():
    async def check():
        transport = _BridgeTransport("session", timeout=1)
        message = JSONRPCMessage.model_validate({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        for _ in range(_EVENT_BUFFER_SIZE):
            transport.buffer_event(message)
        transport._delivered_id = _EVENT_BUFFER_SIZE
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/mcp",
            "headers": [(b"accept", b"text/event-stream"), (b"mcp-session-id", b"session"), (b"last-event-id", b"0")],
        }
        sent = []

        async def receive():
            await anyio.sleep_forever()

        async def send(message):
            if message["type"] == "http.response.start":
                transport.buffer_event(JSONRPCMessage.model_validate({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}))
            else:
                sent.append(message)
                await transport.terminate()

        with anyio.fail_after(2), pytest.raises(RuntimeError, match="history expired during replay"):
            await transport._handle_get_request(Request(scope, receive), send)
        assert sent == []
        assert not transport._events_connected

    anyio.run(check)


@pytest.mark.parametrize("failure", ["closed", "timeout", "partial-closed", "partial-timeout"])
def test_post_transport_failure_never_returns_empty_success_and_preserves_request_id(monkeypatch, failure):
    async def check():
        transport = _BridgeTransport("session", timeout=1)
        messages = []
        scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": []}

        async def receive():
            return {"type": "http.request", "body": b'{"jsonrpc":"2.0","id":"request-id","method":"tools/list"}'}

        async def send(message):
            messages.append(message)

        async def failed_post(self, scope, request, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/event-stream")]})
            if failure.startswith("partial"):
                await send({"type": "http.response.body", "body": b'data: {"jsonrpc":"2.0","method":"notifications/message"}\r\n\r\n', "more_body": True})
            if failure.endswith("timeout"):
                await anyio.sleep_forever()
            await send({"type": "http.response.body", "body": b"", "more_body": False})

        monkeypatch.setattr(StreamableHTTPServerTransport, "_handle_post_request", failed_post)
        with anyio.fail_after(3):
            await transport._handle_post_request(scope, Request(scope, receive), receive, send)
        assert isinstance(transport.failure, TimeoutError if failure.endswith("timeout") else RuntimeError)
        body = b"".join(message.get("body", b"") for message in messages)
        if failure.startswith("partial"):
            assert messages[0]["status"] == 200
            response = json.loads(next(line[5:] for line in body.splitlines() if line.startswith(b"data:") and b'"error"' in line))
        else:
            assert messages[0]["status"] == (504 if failure == "timeout" else 502)
            response = json.loads(body)
        assert response["id"] == "request-id"
        assert response["error"]["code"] == -32603
        assert messages[-1].get("more_body", False) is False

    anyio.run(check)


def test_bridge_cancellation_is_forwarded_while_request_is_pending(bridge, tmp_path):
    headers = _initialize(bridge)
    with ThreadPoolExecutor(max_workers=1) as executor:
        waiting = executor.submit(_rpc, bridge, "fixture/wait", 7, headers=headers)
        deadline = time.monotonic() + 5
        while not (tmp_path / "waiting").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (tmp_path / "waiting").exists()
        assert _rpc(bridge, "notifications/cancelled", None, {"requestId": 7, "reason": "cancel now"}, headers=headers).status_code == 202
        assert _message(waiting.result(timeout=5))["error"] == {"code": -32800, "message": "cancel now"}


def test_bridge_rejects_untrusted_paths_hosts_and_origins(bridge):
    split = urlsplit(bridge.url)
    assert len(split.path.split("/")[1]) >= 32
    assert requests.post(f"http://127.0.0.1:{split.port}/mcp", timeout=5).status_code == 404
    assert requests.post(bridge.url, headers={"Host": "untrusted.example"}, timeout=5).status_code == 421
    assert requests.post(bridge.url, headers={"Origin": "https://untrusted.example"}, timeout=5).status_code == 403


def test_stop_verifies_server_and_descendants_dead_and_endpoint_closed(bridge, tmp_path):
    _initialize(bridge)
    pids = [int((tmp_path / name).read_text()) for name in ("server.pid", "descendant.pid")]
    url = bridge.url
    assert all(_pid_is_running(pid) for pid in pids)
    bridge.stop()
    assert not any(_pid_is_running(pid) for pid in pids)
    with pytest.raises(requests.ConnectionError):
        requests.get(url, timeout=1)


@pytest.mark.parametrize("reply", [{"result": {"roots": []}}, {"error": {"code": -32603, "message": "client failed"}}])
def test_server_notifications_requests_and_client_responses_are_forwarded(bridge, tmp_path, reply):
    headers = _initialize(bridge)
    with requests.get(bridge.url, headers={**_HEADERS, **headers}, stream=True, timeout=5) as stream:
        stream.raise_for_status()
        assert _message(_rpc(bridge, "fixture/events", 8, headers=headers))["result"] == {}
        events = (json.loads(line[5:]) for line in stream.iter_lines() if line.startswith(b"data:"))
        assert next(events)["method"] == "notifications/tools/list_changed"
        assert next(events) == {"jsonrpc": "2.0", "id": "server-request", "method": "roots/list"}
        response = {"jsonrpc": "2.0", "id": "server-request", **reply}
        assert requests.post(bridge.url, headers={**_HEADERS, **headers}, json=response, timeout=5).status_code == 202
        deadline = time.monotonic() + 5
        while not (tmp_path / "server-response.json").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert json.loads((tmp_path / "server-response.json").read_text()) == response


def test_delete_shuts_down_stdio_server_and_descendants(bridge, tmp_path):
    headers = _initialize(bridge)
    assert requests.delete(bridge.url, headers=headers, timeout=5).status_code == 200
    bridge.stop()
    assert not _pid_is_running(int((tmp_path / "server.pid").read_text()))
    assert not _pid_is_running(int((tmp_path / "descendant.pid").read_text()))


@pytest.mark.parametrize("method", ["fixture/crash", "fixture/invalid"])
def test_transport_failure_fails_closed_without_successful_fallback(tmp_path, method):
    bridge = AlMcpBridge({"command": sys.executable, "args": [str(_SERVER)], "env": {}}, tmp_path, timeout_seconds=30).start()
    headers = _initialize(bridge)
    with pytest.raises(requests.RequestException):
        _message(_rpc(bridge, method, 9, headers=headers))
    with pytest.raises(AlMcpBridgeError, match="transport"):
        bridge.stop()
    assert not _pid_is_running(int((tmp_path / "descendant.pid").read_text()))
