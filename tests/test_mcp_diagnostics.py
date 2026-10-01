import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.shared import mcp_diagnostics
from bcbench.agent.shared.diagnostic_process import DiagnosticProcess
from bcbench.agent.shared.mcp_diagnostics import SafeDiagnosticSnapshot, observe_al_catalog

SECRET = "super-secret-token-source-and-password"
SERVER = r"""
import json, os, sys, time
mode = sys.argv[1]
if mode == "exit":
    print("super-secret-token-source-and-password", file=sys.stderr)
    sys.exit(7)
if mode == "framing":
    print("Content-Length: 42", flush=True)
    time.sleep(20)
for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    assert method in ("initialize", "notifications/initialized", "tools/list")
    assert "BC_SERVER_PASSWORD" not in os.environ
    assert "GITHUB_TOKEN" not in os.environ
    assert "UNRELATED_SECRET" not in os.environ
    if method == "notifications/initialized":
        continue
    if method == "initialize":
        if mode == "startup-timeout":
            time.sleep(20)
        print("startup super-secret-token-source-and-password", flush=True)
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}
    else:
        if mode == "timeout" or (mode == "partial" and request["id"] > 2):
            time.sleep(20)
        if mode == "error":
            print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"message": "super-secret-token-source-and-password"}}), flush=True)
            continue
        if mode == "malformed":
            result = {"tools": "super-secret-token-source-and-password"}
        elif mode == "blocked-write":
            result = {"tools": [{"name": "al_publish"}], "nextCursor": "x" * 262144}
        elif mode in ("partial", "pages") and request["id"] == 2:
            result = {"tools": [{"name": "al_publish"}], "nextCursor": "super-secret-token-source-and-password"}
        else:
            names = ["al_run_tests"] if mode == "pages" else ["al_publish", "al_run_tests", "al_compile", "super-secret-token-source-and-password"]
            if mode == "missing":
                names = ["al_compile"]
            result = {"tools": [{"name": name, "description": "super-secret-token-source-and-password", "inputSchema": {"secret": "super-secret-token-source-and-password"}} for name in names]}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
    if mode == "blocked-write" and method == "tools/list":
        time.sleep(20)
"""


def _config(mode: str = "normal") -> str:
    return json.dumps(
        {
            "mcpServers": {
                "altool": {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": ["-u", "-c", SERVER, mode],
                    "env": {"BC_SERVER_PASSWORD": SECRET, "OTHER_SECRET": SECRET},
                }
            }
        }
    )


def test_runtime_catalog_is_observed_safe_and_separate(tmp_path: Path, monkeypatch, caplog):
    monkeypatch.setenv("GITHUB_TOKEN", SECRET)
    monkeypatch.setenv("UNRELATED_SECRET", SECRET)
    monkeypatch.setenv("BC_SERVER_PASSWORD", SECRET)
    caplog.set_level("DEBUG")
    snapshot = SafeDiagnosticSnapshot(tmp_path)
    with patch.object(mcp_diagnostics, "_send", wraps=mcp_diagnostics._send) as send:
        observe_al_catalog(snapshot, _config(), tmp_path, timeout=5)
    artifact = snapshot.path.read_text()
    catalog = json.loads(artifact)["catalog"]
    assert catalog["status"] == "observed"
    assert catalog["complete"] is True
    assert catalog["tool_names"] == ["al_compile", "al_publish", "al_run_tests"]
    assert catalog["target_availability"] == {"al_publish": "present", "al_run_tests": "present"}
    assert catalog["withheld_tool_name_count"] == 1
    assert catalog["model_visibility"] == "unknown"
    assert catalog["process"] == "separate_read_only_discovery_before_agent"
    assert catalog["cleanup"] == "complete"
    assert catalog["ignored_stdout_lines"] == 1
    assert [call.args[1] for call in send.call_args_list] == ["initialize", "notifications/initialized", "tools/list"]
    assert SECRET not in artifact + caplog.text
    assert "description" not in artifact
    assert "tools=['al_compile', 'al_publish', 'al_run_tests']" in caplog.text
    assert list(tmp_path.rglob("*.jsonl")) == []
    assert list(tmp_path.rglob("*.*")) == [snapshot.path]


def test_missing_tools_are_absent_only_after_complete_catalog(tmp_path: Path):
    snapshot = SafeDiagnosticSnapshot(tmp_path)
    assert snapshot.document["catalog"]["target_availability"] == {"al_publish": "unknown", "al_run_tests": "unknown"}
    observe_al_catalog(snapshot, _config("missing"), tmp_path, timeout=5)
    assert snapshot.document["catalog"]["target_availability"] == {"al_publish": "absent", "al_run_tests": "absent"}


def test_catalog_pagination(tmp_path: Path):
    snapshot = SafeDiagnosticSnapshot(tmp_path)
    observe_al_catalog(snapshot, _config("pages"), tmp_path, timeout=5)
    catalog = snapshot.document["catalog"]
    assert catalog["pages_observed"] == 2
    assert catalog["tool_names"] == ["al_publish", "al_run_tests"]
    assert catalog["complete"] is True
    assert SECRET not in snapshot.path.read_text()


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [
        ("malformed", "invalid_tools_list"),
        ("error", "rpc_error"),
        ("exit", "process_exit_before_catalog"),
        ("framing", "unsupported_stdout_framing"),
        ("timeout", "timeout"),
        ("startup-timeout", "timeout"),
    ],
)
def test_catalog_failures_never_claim_missing_or_available_tools(tmp_path: Path, mode: str, expected_error: str, caplog):
    snapshot = SafeDiagnosticSnapshot(tmp_path)
    observe_al_catalog(snapshot, _config(mode), tmp_path, timeout=0.5 if "timeout" in mode else 5)
    catalog = json.loads(snapshot.path.read_text())["catalog"]
    assert catalog["status"] == "failed"
    assert catalog["error_category"] == expected_error
    assert catalog["complete"] is False
    assert catalog["target_availability"] == {"al_publish": "unknown", "al_run_tests": "unknown"}
    assert catalog["cleanup"] == "complete"
    assert SECRET not in snapshot.path.read_text() + caplog.text


def test_partial_catalog_survives_timeout_and_process_is_reaped(tmp_path: Path):
    snapshot = SafeDiagnosticSnapshot(tmp_path)
    processes = []
    real_process = DiagnosticProcess

    def tracked_process(*args, **kwargs):
        process = real_process(*args, **kwargs)
        processes.append(process)
        return process

    with patch.object(mcp_diagnostics, "DiagnosticProcess", side_effect=tracked_process):
        observe_al_catalog(snapshot, _config("partial"), tmp_path, timeout=0.5)
    catalog = json.loads(snapshot.path.read_text())["catalog"]
    assert catalog["pages_observed"] == 1
    assert catalog["tool_names"] == ["al_publish"]
    assert catalog["target_availability"] == {"al_publish": "present", "al_run_tests": "unknown"}
    assert catalog["status"] == "failed"
    assert catalog["error_category"] == "timeout"
    assert processes[0].process.poll() is not None
    assert processes[0].cleanup_complete


def test_catalog_missing_executable_is_safe(tmp_path: Path, caplog):
    config = json.loads(_config())
    config["mcpServers"]["altool"]["command"] = str(tmp_path / SECRET)
    snapshot = SafeDiagnosticSnapshot(tmp_path)
    observe_al_catalog(snapshot, json.dumps(config), tmp_path)
    assert snapshot.document["catalog"]["error_category"] == "startup_or_io_error"
    assert SECRET not in snapshot.path.read_text() + caplog.text


def test_catalog_timeout_also_bounds_blocked_stdin_writes(tmp_path: Path):
    snapshot = SafeDiagnosticSnapshot(tmp_path)
    observe_al_catalog(snapshot, _config("blocked-write"), tmp_path, timeout=0.5)
    catalog = json.loads(snapshot.path.read_text())["catalog"]
    assert catalog["error_category"] == "timeout"
    assert catalog["cleanup"] == "complete"
    assert catalog["pages_observed"] == 1
    assert catalog["target_availability"]["al_run_tests"] == "unknown"


def test_discovery_cannot_send_tool_calls(tmp_path: Path):
    with pytest.raises(mcp_diagnostics._DiscoveryError, match="unsupported_method"):
        mcp_diagnostics._send(None, "tools/call")  # type: ignore[arg-type]


def test_process_timeout_error_does_not_include_command(tmp_path: Path):
    with DiagnosticProcess([sys.executable, "-c", f"import time; secret='{SECRET}'; time.sleep(20)"], tmp_path, {}) as process, pytest.raises(subprocess.TimeoutExpired) as error:
        list(process.lines(0))
    assert SECRET not in str(error.value)
    assert process.process.poll() is not None


def test_snapshot_write_failure_preserves_previous_valid_json_and_does_not_log_paths(tmp_path: Path, caplog):
    snapshot = SafeDiagnosticSnapshot(tmp_path)
    initial = snapshot.path.read_text()
    with patch.object(Path, "replace", side_effect=PermissionError(SECRET)):
        snapshot.document["catalog"]["status"] = "starting"
        snapshot.save()
    assert snapshot.path.read_text() == initial
    assert not snapshot.path.with_suffix(".pending").exists()
    assert SECRET not in caplog.text


def test_snapshot_retries_transient_windows_sharing_violation(tmp_path: Path):
    snapshot = SafeDiagnosticSnapshot(tmp_path)
    replace = Path.replace
    attempts = 0

    def replace_after_reader_closes(path, target):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError(SECRET)
        return replace(path, target)

    with patch.object(Path, "replace", autospec=True, side_effect=replace_after_reader_closes):
        snapshot.document["catalog"]["status"] = "starting"
        snapshot.save()
    assert attempts == 2
    assert json.loads(snapshot.path.read_text())["catalog"]["status"] == "starting"
