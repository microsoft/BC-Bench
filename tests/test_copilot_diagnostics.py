import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.copilot.agent import run_copilot_agent
from bcbench.agent.copilot.cli import invoke_copilot
from bcbench.agent.copilot.diagnostics import CopilotDiagnostics
from bcbench.agent.copilot.metrics import parse_output
from bcbench.agent.shared.diagnostic_process import DiagnosticReadError
from bcbench.agent.shared.mcp_diagnostics import SafeDiagnosticSnapshot
from bcbench.exceptions import AgentError
from bcbench.types import AgentRuntimeConfig, ContainerConfig, EvaluationCategory
from tests.conftest import create_dataset_entry

SECRET = "super-secret-token-source-and-password"


# Structural fixtures verified against installed Copilot 1.0.80/1.0.86
# schemas/session-events.schema.json (ToolExecutionStartData, ToolExecutionCompleteData,
# McpServersLoadedData). 1.0.80 app.js emits result.exitCode and filters session.shutdown from stdout.
# The 36715220745 real transcript confirms altool-al_* names. No raw captured payloads are fixtures.
def _event(kind: str, data: object) -> str:
    return json.dumps({"type": kind, "data": data})


def _start(tool: str = "al_publish", call_id: str = SECRET) -> str:
    return _event("tool.execution_start", {"toolCallId": call_id, "toolName": f"altool-{tool}", "arguments": {"password": SECRET}})


def _complete(success: object = True, result: object = None) -> str:
    return _event(
        "tool.execution_complete",
        {"toolCallId": SECRET, "success": success, "result": result if result is not None else {"content": SECRET}, "error": {"message": SECRET} if success is False else None},
    )


def test_start_completion_and_operation_outcomes_are_distinct(tmp_path: Path):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    diagnostics.observe_line(_start())
    partial = json.loads(diagnostics.snapshot.path.read_text())["agent"]
    assert partial["calls"][0]["execution_outcome"] == "incomplete"
    assert partial["targets"]["al_publish"]["incomplete_count"] == 1
    diagnostics.observe_line(_complete())
    agent = json.loads(diagnostics.snapshot.path.read_text())["agent"]
    assert agent["calls"][0]["execution_outcome"] == "succeeded"
    assert agent["calls"][0]["al_operation_outcome"] == "unavailable"
    assert agent["targets"]["al_publish"]["execution_success_count"] == 1
    assert agent["targets"]["al_publish"]["execution_failure_count"] == 0
    assert agent["targets"]["al_run_tests"]["invocation"] == "not_observed"
    assert agent["targets"]["al_run_tests"]["model_visibility"] == "unknown"
    assert agent["model_reason_for_not_invoking"] == "unavailable"
    assert SECRET not in diagnostics.snapshot.path.read_text()


@pytest.mark.parametrize(
    ("success", "result", "expected"),
    [
        (False, {"content": SECRET}, "failed"),
        (True, {"content": json.dumps({"isError": True, "content": [{"type": "text", "text": SECRET}]})}, "failed"),
        (True, {"content": json.dumps({"isError": False, "content": [{"type": "text", "text": SECRET}]})}, "succeeded"),
        (True, {"isError": True, "content": [{"type": "text", "text": SECRET}]}, "failed"),
        (True, {"isError": False, "content": []}, "unavailable"),
        (True, {"content": json.dumps({"isError": SECRET, "content": []})}, "unavailable"),
        ("true", {"content": SECRET}, "unavailable"),
        (None, {"content": SECRET}, "unavailable"),
        (True, {"message": SECRET}, "unavailable"),
        (True, {"content": {"secret": SECRET}}, "unavailable"),
        (True, SECRET, "unavailable"),
    ],
)
def test_completion_flags_are_strict_and_mcp_semantic_errors_override_success(tmp_path: Path, success, result, expected):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    diagnostics.observe_line(_start())
    diagnostics.observe_line(_complete(success, result))
    assert diagnostics.state["calls"][0]["execution_outcome"] == expected
    assert SECRET not in diagnostics.snapshot.path.read_text()


def test_explicit_mcp_tool_fields_and_unmatched_completion(tmp_path: Path):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    diagnostics.observe_line(
        _event(
            "tool.execution_start",
            {"toolName": SECRET, "toolCallId": SECRET, "mcpServerName": SECRET, "mcpConfigServerName": "altool", "mcpToolName": "al_run_tests"},
        )
    )
    diagnostics.observe_line(_complete(False))
    diagnostics.observe_line(_event("tool.execution_complete", {"mcpServerName": "altool", "mcpToolName": "al_publish", "success": True}))
    assert diagnostics.state["calls"][0]["tool"] == "al_run_tests"
    assert diagnostics.state["targets"]["al_run_tests"]["execution_failure_count"] == 1
    assert diagnostics.state["unmatched_al_completion_count"] == 1
    assert diagnostics.state["targets"]["al_publish"]["invocation"] == "not_observed"


def test_discovery_and_stop_events_are_safe_but_never_a_model_catalog(tmp_path: Path, caplog):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    for line in [
        _event("session.mcp_servers_loaded", {"servers": [{"name": "altool", "status": "connected", "error": SECRET}, {"name": SECRET, "status": SECRET}]}),
        _event("session.mcp_server_status_changed", {"serverName": "altool", "status": "failed", "error": SECRET}),
        _event("session.mcp_server_status_changed", {"serverName": "altool", "status": SECRET}),
        _event("session.tools_updated", {"model": SECRET, "tools": [{"name": "al_publish"}]}),
        _event("session.error", {"errorType": "quota", "message": SECRET, "errorCode": SECRET}),
        _event("session.error", {"errorType": SECRET, "message": SECRET}),
        _event("session.shutdown", {"shutdownType": "error", "errorReason": SECRET}),
        json.dumps({"type": "result", "exitCode": 1, "reason": SECRET, "sessionId": SECRET}),
        _event("assistant.message", {"content": SECRET}),
        _event("tool.execution_start", {"toolName": SECRET, "arguments": SECRET}),
        _event(SECRET, {SECRET: SECRET}),
        SECRET,
        json.dumps([SECRET]),
    ]:
        diagnostics.observe_line(line)
    assert diagnostics.state["server_status_observations"] == ["connected", "failed", "unknown"]
    assert diagnostics.state["model_tool_catalog"] == "unobserved"
    assert diagnostics.state["stop"]["result_exit"] == "failure"
    assert diagnostics.state["stop"]["shutdown_event"] == "error"
    assert diagnostics.state["stop"]["session_errors"] == ["quota", "unclassified"]
    assert diagnostics.state["invalid_event_count"] == 3
    assert SECRET not in diagnostics.snapshot.path.read_text() + caplog.text


@pytest.mark.parametrize("mode", ["timeout", "failure"])
def test_streamed_partial_progress_survives_failure_and_timeout(tmp_path: Path, mode: str, caplog):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    script = f"import sys,time;print({_start()!r},flush=True);print({SECRET!r},file=sys.stderr,flush=True);" + ("time.sleep(20)" if mode == "timeout" else "sys.exit(7)")
    expected_error = subprocess.TimeoutExpired if mode == "timeout" else subprocess.CalledProcessError
    with pytest.raises(expected_error) as error:
        diagnostics.run([sys.executable, "-u", "-c", script], tmp_path, {}, 0.5 if mode == "timeout" else 5)
    agent = json.loads(diagnostics.snapshot.path.read_text())["agent"]
    assert agent["calls"][0]["completion"] == "not_observed"
    assert agent["stop"]["process"] == ("timeout" if mode == "timeout" else "exited_nonzero")
    assert agent["stop"]["result_event"] == "unobserved"
    assert agent["stop"]["cleanup"] == "complete"
    assert SECRET not in diagnostics.snapshot.path.read_text() + caplog.text + str(error.value)


def test_snapshot_is_durable_while_subprocess_is_still_running(tmp_path: Path):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    script = f"""
import json, pathlib, time
import sys
assert sys.stdin.read() == ""
print({_start()!r}, flush=True)
path = pathlib.Path({str(diagnostics.snapshot.path)!r})
for _ in range(100):
    if json.loads(path.read_text())["agent"]["calls"]:
        print('{{"type":"result","exitCode":0}}', flush=True)
        break
    time.sleep(0.01)
else:
    raise SystemExit(7)
"""
    diagnostics.run([sys.executable, "-u", "-c", script], tmp_path, {}, 5)
    agent = json.loads(diagnostics.snapshot.path.read_text())["agent"]
    assert agent["stop"]["process"] == "exited_zero"
    assert agent["stop"]["result_exit"] == "success"
    assert agent["stop"]["shutdown_event"] == "unobserved"
    assert agent["targets"]["al_run_tests"]["invocation"] == "not_invoked_in_observed_stream"


def test_missing_cli_leaves_explicit_stop_evidence(tmp_path: Path):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    with patch("bcbench.agent.copilot.cli._find_copilot", return_value=None), pytest.raises(AgentError, match="not found"):
        invoke_copilot(prompt=SECRET, model="test", work_dir=tmp_path, timeout=1, diagnostics=diagnostics)
    assert json.loads(diagnostics.snapshot.path.read_text())["agent"]["stop"]["process"] == "executable_unavailable"


def test_conflicting_mcp_server_does_not_count_as_al_invocation(tmp_path: Path):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    diagnostics.observe_line(_event("tool.execution_start", {"toolName": "altool-al_publish", "mcpServerName": SECRET, "toolCallId": SECRET}))
    assert diagnostics.state["calls"] == []


def test_contradictory_completion_payload_is_not_reported_as_success(tmp_path: Path):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    diagnostics.observe_line(_start())
    diagnostics.observe_line(_event("tool.execution_complete", {"toolCallId": SECRET, "success": True, "result": {"content": SECRET}, "error": {"message": SECRET}}))
    assert diagnostics.state["calls"][0]["execution_outcome"] == "unavailable"


def test_metrics_and_transcript_parsing_are_unchanged_with_diagnostics(tmp_path: Path, caplog):
    stdout = "\n".join(
        [
            _event("model.call_start", {"turnId": "0"}),
            _start(),
            _complete(False),
            _event("assistant.message", {"content": "done", "phase": "final_answer"}),
            _event("session.usage_checkpoint", {"totalNanoAiu": 1230000000}),
            json.dumps({"type": "result", "exitCode": 0, "usage": {"sessionDurationMs": 4000, "totalApiDurationMs": 2000}}),
        ]
    )
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    caplog.set_level("DEBUG")
    with (
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch.object(diagnostics, "run", return_value=stdout),
        patch("bcbench.agent.copilot.cli.subprocess.run") as run,
    ):
        metrics, response = invoke_copilot(prompt=SECRET, model="test", work_dir=tmp_path, timeout=5, diagnostics=diagnostics)
    assert (metrics, response) == parse_output(stdout.splitlines())
    assert metrics.tool_usage == {"altool-al_publish": 1}
    assert "Copilot: done" in caplog.messages
    assert SECRET not in caplog.text
    run.assert_not_called()


@pytest.mark.parametrize("enabled", [True, False])
def test_agent_wires_diagnostics_only_for_al_mcp_and_continues_after_discovery_failure(tmp_path: Path, enabled: bool):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    output_dir = tmp_path / "output"
    runtime = AgentRuntimeConfig(container=ContainerConfig("test", "", "", "CRONUS"), al_mcp=enabled)

    def invoke(**kwargs):
        diagnostics = kwargs["diagnostics"]
        if enabled:
            assert isinstance(diagnostics, CopilotDiagnostics)
            catalog = json.loads(diagnostics.snapshot.path.read_text())["catalog"]
            assert catalog["status"] == "failed"
            assert catalog["error_category"] == "stdio_configuration_unavailable"
        else:
            assert diagnostics is None
        return None, ""

    with (
        patch("bcbench.agent.copilot.agent.build_prompt", return_value=SECRET),
        patch("bcbench.agent.copilot.agent.build_mcp_config", return_value=(None, None)),
        patch("bcbench.agent.copilot.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.copilot.agent.setup_instructions_from_config", return_value=False),
        patch("bcbench.agent.copilot.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.copilot.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.copilot.agent.resolve_config_plugins", return_value=[]),
        patch("bcbench.agent.copilot.agent.invoke_copilot", side_effect=invoke),
    ):
        run_copilot_agent(create_dataset_entry(), "test-model", EvaluationCategory.BUG_FIX, repo_path, output_dir, runtime)
    assert (output_dir / "diagnostics" / "al-mcp.json").exists() is enabled


def test_timeout_cleans_descendants_holding_stdout_open(tmp_path: Path):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    script = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'],stdout=sys.stdout,stderr=sys.stderr);print({_start()!r},flush=True);time.sleep(20)"
    with pytest.raises(subprocess.TimeoutExpired):
        diagnostics.run([sys.executable, "-u", "-c", script], tmp_path, {}, 0.5)
    assert diagnostics.state["stop"]["cleanup"] == "complete"
    assert diagnostics.state["targets"]["al_publish"]["incomplete_count"] == 1


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (f"HTTP 401 Unauthorized: {SECRET}", ["authentication"]),
        (f"HTTP 403 Forbidden: {SECRET}", ["authorization"]),
        (f"ECONNREFUSED {SECRET}", ["connection"]),
        (f"Request timed out: {SECRET}", ["timeout"]),
        (f"error AL1022: Package {SECRET} could not be found", ["compilation", "dependency"]),
        (SECRET, []),
    ],
)
def test_error_markers_retain_fixed_labels_not_sensitive_details(tmp_path: Path, message: str, expected: list[str]):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    diagnostics.observe_line(_start())
    diagnostics.observe_line(_event("tool.execution_complete", {"toolCallId": SECRET, "success": False, "error": {"message": message, "code": SECRET}}))
    assert diagnostics.state["calls"][0]["reported_error_markers"] == expected
    assert diagnostics.state["calls"][0]["error_details"] == "withheld"
    assert SECRET not in diagnostics.snapshot.path.read_text()


def test_mcp_error_envelope_markers_are_not_extracted_from_successful_result_text(tmp_path: Path):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    text = f"Compilation failed: {SECRET}"
    diagnostics.observe_line(_start())
    diagnostics.observe_line(_complete(True, {"content": text}))
    assert diagnostics.state["calls"][0]["reported_error_markers"] == []
    diagnostics.observe_line(_start())
    diagnostics.observe_line(_complete(True, {"content": json.dumps({"isError": True, "content": [{"type": "text", "text": text}]})}))
    assert diagnostics.state["calls"][1]["reported_error_markers"] == ["compilation"]
    assert SECRET not in diagnostics.snapshot.path.read_text()


def test_server_and_session_error_markers_do_not_copy_text(tmp_path: Path):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    diagnostics.observe_line(_event("session.mcp_server_status_changed", {"serverName": "altool", "status": "failed", "error": f"Connection refused: {SECRET}"}))
    diagnostics.observe_line(_event("session.error", {"errorType": "authentication", "message": f"Unauthorized: {SECRET}"}))
    assert diagnostics.state["server_error_markers"] == ["connection"]
    assert diagnostics.state["stop"]["reported_error_markers"] == ["authentication"]
    assert SECRET not in diagnostics.snapshot.path.read_text()


def test_startup_exception_does_not_leak_sensitive_command_details(tmp_path: Path, caplog):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    with patch("bcbench.agent.copilot.diagnostics.DiagnosticProcess", side_effect=OSError(SECRET)), pytest.raises(DiagnosticReadError) as error:
        diagnostics.run(["copilot", SECRET], tmp_path, {}, 5)
    assert diagnostics.state["stop"]["process"] == "startup_or_io_error"
    assert SECRET not in str(error.value) + diagnostics.snapshot.path.read_text() + caplog.text


@pytest.mark.parametrize(
    "line",
    [
        _event("tool.execution_start", SECRET),
        _event("tool.execution_start", {"toolName": "altool-al_publish"}),
        _event("tool.execution_complete", {"mcpServerName": "altool", "mcpToolName": "al_publish", "success": False}),
    ],
)
def test_malformed_tool_events_never_establish_absence(tmp_path: Path, line: str):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    diagnostics.observe_line(line)
    diagnostics.state["stream"] = "eof"
    diagnostics.save()
    assert diagnostics.state["invalid_event_count"] == 1
    assert diagnostics.state["targets"]["al_run_tests"]["invocation"] == "not_observed"
