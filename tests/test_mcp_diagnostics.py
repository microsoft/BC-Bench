import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.diagnostics.mcp_diagnostics import SafeDiagnosticSnapshot, observe_al_connection
from bcbench.diagnostics.mcp_observation import MAX_FRAME_BYTES, McpObservation

SECRET = "super-secret-token-source-and-password"


def _wire(message):
    return json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False).encode() + b"\n"


def _observer(tmp_path):
    return McpObservation(SafeDiagnosticSnapshot(tmp_path, invocation_id="a" * 32, connection_id="b" * 32))


def test_wrapper_preserves_configuration_and_does_not_launch_a_probe(tmp_path: Path):
    original = {
        "mcpServers": {
            "altool": {"type": "stdio", "command": "al", "args": ["launchmcpserver", r"C:\project with spaces"], "env": {"BC_SERVER_PASSWORD": SECRET}, "tools": ["*"]},
            "other": {"type": "http", "url": "http://localhost"},
        }
    }
    snapshot = SafeDiagnosticSnapshot(tmp_path)
    with patch("subprocess.Popen") as popen:
        wrapped = json.loads(observe_al_connection(json.dumps(original), snapshot))
    popen.assert_not_called()
    server = wrapped["mcpServers"]["altool"]
    assert server["command"] == sys.executable
    assert server["args"][-3:] == ["al", "launchmcpserver", r"C:\project with spaces"]
    assert server["env"] == original["mcpServers"]["altool"]["env"]
    assert server["tools"] == ["*"]
    assert wrapped["mcpServers"]["other"] == original["mcpServers"]["other"]
    assert SECRET not in snapshot.path.read_text()


def test_lists_are_independent_observations_not_a_reconstructed_current_catalog(tmp_path: Path):
    observer = _observer(tmp_path)
    for request_id, params in [(1, {}), ("1", {}), (2, {"cursor": SECRET})]:
        observer.feed("client", _wire({"id": request_id, "method": "tools/list", "params": params}))
    for request_id, result in [
        ("1", {"tools": []}),
        (1, {"tools": [{"name": "al_publish", "description": SECRET}, {"name": SECRET}], "nextCursor": SECRET}),
        (2, {"tools": [{"name": "al_run_tests", "inputSchema": {"secret": SECRET}}]}),
    ]:
        observer.feed("server", _wire({"id": request_id, "result": result}))
    observer.save()
    first, second, continuation = observer.state["lists"]
    assert first == {"sequence": 1, "initial_page": True, "status": "observed", "has_next_page": True, "tool_count": 2, "tool_names": ["al_publish"]}
    assert second["tool_names"] == []
    assert second["has_next_page"] is False
    assert continuation["initial_page"] is False
    assert continuation["tool_names"] == ["al_run_tests"]
    assert observer.state["model_visibility"] == "unknown"
    assert SECRET not in observer.snapshot.path.read_text()


def test_target_requests_are_counted_without_parsing_outcomes(tmp_path: Path):
    observer = _observer(tmp_path)
    for index, tool in enumerate(["al_publish", "al_run_tests", "al_compile", SECRET]):
        observer.feed("client", _wire({"id": index, "method": "tools/call", "params": {"name": tool, "arguments": {"secret": SECRET}}}))
        observer.feed("server", _wire({"id": index, "result": {"isError": True, "content": [{"text": SECRET}]}}))
    observer.save()
    assert observer.state["target_call_requests"] == {"al_publish": 1, "al_run_tests": 1}
    assert "calls" not in observer.state
    assert SECRET not in observer.snapshot.path.read_text()


@pytest.mark.parametrize(("response", "status"), [({"error": {"message": SECRET}}, "rpc_error"), ({"result": {"tools": SECRET}}, "malformed"), (None, "unobserved")])
def test_missing_or_bad_list_responses_do_not_become_empty_catalogs(tmp_path: Path, response, status):
    observer = _observer(tmp_path)
    observer.feed("client", _wire({"id": SECRET, "method": "tools/list"}))
    if response is not None:
        observer.feed("server", _wire({"id": SECRET, **response}))
    observer.save()
    assert observer.state["lists"][0]["status"] == status
    assert "tool_names" not in observer.state["lists"][0]
    assert SECRET not in observer.snapshot.path.read_text()


@pytest.mark.parametrize("wire", [b"\xff invalid\n", b"x" * (MAX_FRAME_BYTES + 1) + b"\n", b'{"jsonrpc":'], ids=["malformed", "oversized", "partial"])
def test_invalid_or_partial_framing_marks_evidence_incomplete(tmp_path: Path, wire: bytes):
    observer = _observer(tmp_path)
    observer.feed("server", wire)
    observer.eof("server")
    observer.eof("client")
    observer.save()
    assert observer.state["observation_issues"]
    assert observer.state["observation_complete"] is False


def test_fragmented_unicode_frames_and_server_initiated_requests(tmp_path: Path):
    observer = _observer(tmp_path)
    request = _wire({"id": 7, "method": "tools/list"})
    response = _wire({"id": 7, "result": {"tools": [{"name": "al_run_tests", "description": "Unicode: \u00f8"}]}})
    for byte in request:
        observer.feed("client", bytes([byte]))
    observer.feed("server", _wire({"id": 7, "method": "sampling/createMessage", "params": {"secret": SECRET}}))
    for byte in response:
        observer.feed("server", bytes([byte]))
    observer.save()
    assert observer.state["lists"][0]["tool_names"] == ["al_run_tests"]
    assert SECRET not in observer.snapshot.path.read_text()


def test_duplicate_ids_and_record_limits_do_not_invent_responses(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("bcbench.diagnostics.mcp_observation.MAX_RECORDS", 2)
    observer = _observer(tmp_path)
    for request_id in [1, 1, 2, 3]:
        observer.feed("client", _wire({"id": request_id, "method": "tools/list"}))
    observer.save()
    assert len(observer.state["lists"]) == 2
    assert observer.state["lists"][0]["status"] == "ambiguous_request_id"
    assert observer.state["observation_issues"] == ["ambiguous_request_id", "record_limit"]


def test_snapshot_isolation_and_failed_write_preserve_existing_data(tmp_path: Path, caplog):
    parent = SafeDiagnosticSnapshot(tmp_path)
    first = SafeDiagnosticSnapshot(tmp_path, invocation_id=parent.invocation_id, connection_id="a" * 32)
    second = SafeDiagnosticSnapshot(tmp_path, invocation_id=parent.invocation_id, connection_id="b" * 32)
    assert len({parent.path, first.path, second.path}) == 3
    initial = first.path.read_text()
    with patch.object(Path, "replace", side_effect=PermissionError(SECRET)):
        first.document["extra"] = "new data"
        first.save()
    assert first.path.read_text() == initial
    assert not first.path.with_suffix(".pending").exists()
    assert SECRET not in caplog.text
    assert not list(tmp_path.rglob("*.jsonl"))
