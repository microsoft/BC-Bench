import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests

from bcbench.agent.shared.al_mcp_bridge import AlMcpBridge, AlMcpBridgeError
from tests.test_contained_process import _pid_is_running

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects are required")
_SERVER = Path(__file__).parent / "fixtures" / "stdio_mcp_server.py"
_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def bridge(tmp_path):
    server = {"command": sys.executable, "args": [str(_SERVER)], "env": {"BC_SERVER_PASSWORD": "bridge-only-bc-secret"}}
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


def test_server_notifications_requests_and_client_responses_are_forwarded(bridge, tmp_path):
    headers = _initialize(bridge)
    with requests.get(bridge.url, headers={**_HEADERS, **headers}, stream=True, timeout=5) as stream:
        stream.raise_for_status()
        assert _message(_rpc(bridge, "fixture/events", 8, headers=headers))["result"] == {}
        events = (json.loads(line[5:]) for line in stream.iter_lines() if line.startswith(b"data:"))
        assert next(events)["method"] == "notifications/tools/list_changed"
        assert next(events) == {"jsonrpc": "2.0", "id": "server-request", "method": "roots/list"}
        response = {"jsonrpc": "2.0", "id": "server-request", "result": {"roots": []}}
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
    with pytest.raises((requests.RequestException, StopIteration)):
        _message(_rpc(bridge, method, 9, headers=headers))
    with pytest.raises(AlMcpBridgeError, match="transport"):
        bridge.stop()
    assert not _pid_is_running(int((tmp_path / "descendant.pid").read_text()))
