import subprocess
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pytest

from bcbench_core.agent.copilot import CopilotOptions, CopilotProcessError, CopilotTimeoutError, invoke_copilot
from bcbench_core.agent.copilot.agent import _find_copilot
from bcbench_core.exceptions import AgentError


def test_invoke_copilot_defaults_to_none_tool_argument_and_no_custom_instructions(tmp_path: Path):
    with (
        patch("bcbench_core.agent.copilot.agent._find_copilot", return_value="copilot"),
        patch("bcbench_core.agent.copilot.agent.parse_output", return_value=(None, None)),
        patch(
            "bcbench_core.agent.copilot.agent.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='{"type":"result"}\n', stderr=""),
        ) as mock_run,
    ):
        invoke_copilot(prompt="do the task", model="test-model", work_dir=tmp_path, timeout=60, env={})

    assert mock_run.call_args.args[0] == [
        "copilot",
        "--output-format=json",
        "--available-tools=none",
        "--disable-builtin-mcps",
        "--no-custom-instructions",
        "--model=test-model",
        "--prompt=do the task",
    ]
    assert mock_run.call_args.kwargs["env"] == {}


def test_invoke_copilot_can_enable_custom_instructions(tmp_path: Path):
    with (
        patch("bcbench_core.agent.copilot.agent._find_copilot", return_value="copilot"),
        patch("bcbench_core.agent.copilot.agent.parse_output", return_value=(None, None)),
        patch(
            "bcbench_core.agent.copilot.agent.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='{"type":"result"}\n', stderr=""),
        ) as mock_run,
    ):
        invoke_copilot(
            prompt="do the task",
            model="test-model",
            work_dir=tmp_path,
            timeout=60,
            env={},
            options=CopilotOptions(custom_instructions=True),
        )

    assert "--no-custom-instructions" not in mock_run.call_args.args[0]


def test_invoke_copilot_logs_readable_transcript(tmp_path: Path, caplog):
    output = '{"type":"model.call_start","data":{"turnId":"0"}}\n{"type":"assistant.message","data":{"content":"working"}}\n{"type":"result"}\n'
    caplog.set_level("INFO")
    with (
        patch("bcbench_core.agent.copilot.agent._find_copilot", return_value="copilot"),
        patch(
            "bcbench_core.agent.copilot.agent.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=output, stderr=""),
        ),
    ):
        invoke_copilot(prompt="do the task", model="test-model", work_dir=tmp_path, timeout=60, env={})

    assert "Copilot: working" in caplog.messages
    assert output not in caplog.text


def test_find_copilot_prefers_the_exe_over_script_shims():
    with patch("bcbench_core.agent.copilot.agent.shutil.which", side_effect=lambda name: name if name in ("copilot.exe", "copilot") else None):
        assert _find_copilot() == "copilot.exe"


def test_invoke_copilot_requires_the_cli(tmp_path: Path):
    with patch("bcbench_core.agent.copilot.agent._find_copilot", return_value=None), pytest.raises(AgentError, match="Copilot CLI not found"):
        invoke_copilot(prompt="p", model="m", work_dir=tmp_path, timeout=60, env={})


def test_invoke_copilot_forwards_cli_stderr(tmp_path: Path, capsys):
    with (
        patch("bcbench_core.agent.copilot.agent._find_copilot", return_value="copilot"),
        patch(
            "bcbench_core.agent.copilot.agent.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="warning: slow model\n"),
        ),
    ):
        assert invoke_copilot(prompt="p", model="m", work_dir=tmp_path, timeout=60, env={}) == (None, "")

    assert "warning: slow model" in capsys.readouterr().err


def _command_for(options: CopilotOptions, tmp_path: Path) -> list[str]:
    with (
        patch("bcbench_core.agent.copilot.agent._find_copilot", return_value="copilot"),
        patch("bcbench_core.agent.copilot.agent.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")) as run,
    ):
        invoke_copilot("p", "m", tmp_path, 60, {}, options)
    command = run.call_args.args[0]
    assert isinstance(command, list)
    return [str(arg) for arg in command]


def test_invoke_copilot_adds_logging_only_with_a_log_dir(tmp_path: Path):
    assert _command_for(CopilotOptions(), tmp_path)[6:-1] == []
    assert _command_for(CopilotOptions(log_dir=tmp_path), tmp_path)[6:-1] == ["--log-level=debug", f"--log-dir={tmp_path.resolve()}"]
    assert _command_for(CopilotOptions(mcp_config_json='{"mcpServers":{}}'), tmp_path)[6:-1] == ['--additional-mcp-config={"mcpServers":{}}']


def test_invoke_copilot_does_not_grant_plugin_directory_access(tmp_path: Path):
    command = _command_for(CopilotOptions(plugin_dirs=(tmp_path / "plugin",)), tmp_path)

    assert f"--plugin-dir={tmp_path / 'plugin'}" in command
    assert not any(arg.startswith("--add-dir=") for arg in command)


def test_invoke_copilot_runs_a_configured_session_without_caller_built_arguments(tmp_path: Path):
    options = CopilotOptions(
        allow_all_tools=True,
        custom_instructions=True,
        log_dir=tmp_path / "logs",
        mcp_config_json='{"mcpServers":{}}',
        plugin_dirs=(tmp_path / "lsp", tmp_path / "plugin with spaces"),
        granted_dirs=(tmp_path / "plugin with spaces",),
        custom_agent="al-dev",
        workspace_mcp=True,
        extra_args=("--test-extra-arg",),
    )
    output = '{"type":"model.call_start"}\n{"type":"assistant.message","data":{"content":"done","phase":"final_answer"}}\n'
    parent_env = MappingProxyType({"PATH": "explicit"})
    with (
        patch("bcbench_core.agent.copilot.agent._find_copilot", return_value="copilot"),
        patch(
            "bcbench_core.agent.copilot.agent.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr=""),
        ) as run,
    ):
        metrics, response = invoke_copilot('line one\r\n"line two"', "test-model", tmp_path, 60, parent_env, options)

    assert response == "done"
    assert metrics is not None
    assert metrics.turn_count == 1
    assert run.call_args.args[0] == [
        "copilot",
        "--output-format=json",
        "--allow-all-tools",
        "--disable-builtin-mcps",
        "--model=test-model",
        "--log-level=debug",
        f"--log-dir={(tmp_path / 'logs').resolve()}",
        '--additional-mcp-config={"mcpServers":{}}',
        f"--plugin-dir={tmp_path / 'lsp'}",
        f"--plugin-dir={tmp_path / 'plugin with spaces'}",
        f"--add-dir={tmp_path / 'plugin with spaces'}",
        "--agent=al-dev",
        "--test-extra-arg",
        '--prompt=line one "line two"',
    ]
    assert run.call_args.kwargs == {
        "cwd": str(tmp_path),
        "env": {"PATH": "explicit", "GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": "true"},
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": 60,
        "check": True,
    }
    assert parent_env == {"PATH": "explicit"}


@pytest.mark.parametrize(("workspace_mcp", "expected"), [(None, "inherited"), (True, "true"), (False, "false")])
def test_workspace_mcp_option_preserves_or_overrides_supplied_environment(tmp_path: Path, workspace_mcp: bool | None, expected: str):
    parent_env = {"GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": "inherited"}
    with (
        patch("bcbench_core.agent.copilot.agent._find_copilot", return_value="copilot"),
        patch(
            "bcbench_core.agent.copilot.agent.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ) as run,
    ):
        invoke_copilot("p", "m", tmp_path, 60, parent_env, CopilotOptions(workspace_mcp=workspace_mcp))

    assert run.call_args.kwargs["env"] == {"GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": expected}
    assert parent_env == {"GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": "inherited"}


@pytest.mark.parametrize(("stdout", "stderr"), [("partial output", "model unavailable"), (b"partial output", b"model unavailable")])
def test_invoke_copilot_preserves_process_failure_diagnostics(tmp_path: Path, stdout: str | bytes, stderr: str | bytes, caplog):
    failure = subprocess.CalledProcessError(2, ["copilot"], output=stdout, stderr=stderr)
    with (
        patch("bcbench_core.agent.copilot.agent._find_copilot", return_value="copilot"),
        patch("bcbench_core.agent.copilot.agent.subprocess.run", side_effect=failure),
        pytest.raises(CopilotProcessError, match="exit status 2") as error,
    ):
        invoke_copilot("p", "m", tmp_path, 60, {})

    assert error.value.returncode == 2
    assert error.value.stdout == stdout
    assert error.value.stderr == stderr
    assert error.value.__cause__ is failure
    assert "Copilot CLI execution failed" in caplog.text


def test_invoke_copilot_reports_timeout_with_metrics_and_partial_output(tmp_path: Path, caplog):
    failure = subprocess.TimeoutExpired(["copilot"], 60, output=b"partial output", stderr=b"waiting")
    with (
        patch("bcbench_core.agent.copilot.agent._find_copilot", return_value="copilot"),
        patch("bcbench_core.agent.copilot.agent.subprocess.run", side_effect=failure),
        pytest.raises(CopilotTimeoutError, match="after 60 seconds") as error,
    ):
        invoke_copilot("p", "m", tmp_path, 60, {})

    assert error.value.timeout == 60
    assert error.value.metrics.execution_time == 60
    assert error.value.stdout == b"partial output"
    assert error.value.stderr == b"waiting"
    assert error.value.__cause__ is failure
    assert "Copilot CLI timed out" in caplog.text


def test_invoke_copilot_reports_launch_failure(tmp_path: Path, caplog):
    failure = OSError("unavailable")
    with (
        patch("bcbench_core.agent.copilot.agent._find_copilot", return_value="copilot"),
        patch("bcbench_core.agent.copilot.agent.subprocess.run", side_effect=failure),
        pytest.raises(CopilotProcessError, match="Could not start Copilot CLI: unavailable") as error,
    ):
        invoke_copilot("p", "m", tmp_path, 60, {})

    assert error.value.returncode is None
    assert error.value.__cause__ is failure
    assert "Could not start Copilot CLI" in caplog.text
