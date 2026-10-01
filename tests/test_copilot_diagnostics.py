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
from bcbench.diagnostics.mcp_diagnostics import SafeDiagnosticSnapshot
from bcbench.exceptions import AgentError
from bcbench.types import AgentRuntimeConfig, ContainerConfig, EvaluationCategory
from tests.conftest import create_dataset_entry

SECRET = "super-secret-token-source-and-password"


@pytest.mark.parametrize("timeout", [True, False])
def test_process_failure_records_status_without_sensitive_command(tmp_path: Path, timeout: bool, caplog):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    script = f"import sys,time;print({SECRET!r},file=sys.stderr,flush=True);" + ("time.sleep(20)" if timeout else "sys.exit(7)")
    expected_error = subprocess.TimeoutExpired if timeout else subprocess.CalledProcessError
    with pytest.raises(expected_error) as error:
        diagnostics.run([sys.executable, "-u", "-c", script], tmp_path, {}, 0.5 if timeout else 5)
    assert diagnostics.state["process"] == ("timeout" if timeout else "exited")
    assert diagnostics.state["exit_code"] == (None if timeout else 7)
    assert diagnostics.state["cleanup"] == "complete"
    assert SECRET not in diagnostics.snapshot.path.read_text() + caplog.text + str(error.value)


def test_runner_returns_original_stdout_without_copying_it_to_snapshot(tmp_path: Path):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    stdout = diagnostics.run([sys.executable, "-u", "-c", f"print({SECRET!r})"], tmp_path, {}, 5)
    assert stdout == SECRET + "\n"
    assert diagnostics.state == {"process": "exited", "exit_code": 0, "cleanup": "complete"}
    assert SECRET not in diagnostics.snapshot.path.read_text()


def test_missing_executable_and_startup_errors_are_safe(tmp_path: Path, caplog):
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    with patch("bcbench.agent.copilot.cli._find_copilot", return_value=None), pytest.raises(AgentError, match="not found"):
        invoke_copilot(prompt=SECRET, model="test", work_dir=tmp_path, timeout=1, diagnostics=diagnostics)
    assert diagnostics.state["process"] == "executable_unavailable"
    with patch("bcbench.agent.copilot.diagnostics.DiagnosticProcess", side_effect=OSError(SECRET)), pytest.raises(DiagnosticReadError) as error:
        diagnostics.run(["copilot", SECRET], tmp_path, {}, 5)
    assert diagnostics.state["process"] == "startup_or_io_error"
    assert SECRET not in str(error.value) + diagnostics.snapshot.path.read_text() + caplog.text


def test_existing_metrics_and_transcript_parsing_remain_the_only_cli_event_analysis(tmp_path: Path, caplog):
    stdout = "\n".join(
        json.dumps(event)
        for event in [
            {"type": "model.call_start", "data": {}},
            {"type": "tool.execution_start", "data": {"toolName": "altool-al_publish", "arguments": {"password": SECRET}}},
            {"type": "assistant.message", "data": {"content": "done", "phase": "final_answer"}},
            {"type": "result", "usage": {"sessionDurationMs": 4000, "totalApiDurationMs": 2000}},
        ]
    )
    diagnostics = CopilotDiagnostics(SafeDiagnosticSnapshot(tmp_path))
    caplog.set_level("DEBUG")
    with (
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch.object(diagnostics, "run", return_value=stdout),
        patch("bcbench.agent.copilot.cli.subprocess.run") as run,
    ):
        result = invoke_copilot(prompt=SECRET, model="test", work_dir=tmp_path, timeout=5, diagnostics=diagnostics)
    assert result == parse_output(stdout.splitlines())
    assert "Copilot: done" in caplog.messages
    assert SECRET not in caplog.text
    run.assert_not_called()


@pytest.mark.parametrize(("al_mcp", "opt_in"), [(False, False), (False, True), (True, False), (True, True)])
def test_diagnostics_require_explicit_opt_in_and_al_mcp(tmp_path: Path, monkeypatch, al_mcp: bool, opt_in: bool):
    monkeypatch.delenv("BCBENCH_AL_MCP_DIAGNOSTICS", raising=False)
    if opt_in:
        monkeypatch.setenv("BCBENCH_AL_MCP_DIAGNOSTICS", "1")
    runtime = AgentRuntimeConfig(container=ContainerConfig("test", "", "", "CRONUS"), al_mcp=al_mcp)

    def invoke(**kwargs):
        assert (kwargs["diagnostics"] is not None) is (al_mcp and opt_in)
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
        run_copilot_agent(create_dataset_entry(), "test-model", EvaluationCategory.BUG_FIX, tmp_path, tmp_path, runtime)
    assert (tmp_path / "diagnostics" / "al-mcp.json").exists() is (al_mcp and opt_in)
