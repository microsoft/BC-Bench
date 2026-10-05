import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench_core.agent.copilot.cli import _find_copilot, copilot_session_args, invoke_copilot
from bcbench_core.exceptions import AgentError


def test_invoke_copilot_defaults_to_none_tool_argument_and_no_custom_instructions(tmp_path: Path):
    with (
        patch("bcbench_core.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench_core.agent.copilot.cli.parse_output", return_value=(None, None)),
        patch(
            "bcbench_core.agent.copilot.cli.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='{"type":"result"}\n', stderr=""),
        ) as mock_run,
    ):
        invoke_copilot(prompt="do the task", model="test-model", work_dir=tmp_path, timeout=60)

    assert mock_run.call_args.args[0] == [
        "copilot",
        "--output-format=json",
        "--available-tools=none",
        "--disable-builtin-mcps",
        "--no-custom-instructions",
        "--model=test-model",
        "--prompt=do the task",
    ]


def test_invoke_copilot_can_enable_custom_instructions(tmp_path: Path):
    with (
        patch("bcbench_core.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench_core.agent.copilot.cli.parse_output", return_value=(None, None)),
        patch(
            "bcbench_core.agent.copilot.cli.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='{"type":"result"}\n', stderr=""),
        ) as mock_run,
    ):
        invoke_copilot(
            prompt="do the task",
            model="test-model",
            work_dir=tmp_path,
            timeout=60,
            custom_instructions=True,
        )

    assert "--no-custom-instructions" not in mock_run.call_args.args[0]


def test_invoke_copilot_logs_readable_transcript(tmp_path: Path, caplog):
    output = '{"type":"model.call_start","data":{"turnId":"0"}}\n{"type":"assistant.message","data":{"content":"working"}}\n{"type":"result"}\n'
    caplog.set_level("INFO")
    with (
        patch("bcbench_core.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch(
            "bcbench_core.agent.copilot.cli.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=output, stderr=""),
        ),
    ):
        invoke_copilot(prompt="do the task", model="test-model", work_dir=tmp_path, timeout=60)

    assert "Copilot: working" in caplog.messages
    assert output not in caplog.text


def test_find_copilot_prefers_the_exe_over_script_shims():
    with patch("bcbench_core.agent.copilot.cli.shutil.which", side_effect=lambda name: name if name in ("copilot.exe", "copilot") else None):
        assert _find_copilot() == "copilot.exe"


def test_invoke_copilot_requires_the_cli(tmp_path: Path):
    with patch("bcbench_core.agent.copilot.cli._find_copilot", return_value=None), pytest.raises(AgentError, match="Copilot CLI not found"):
        invoke_copilot(prompt="p", model="m", work_dir=tmp_path, timeout=60)


def test_invoke_copilot_forwards_cli_stderr(tmp_path: Path, capsys):
    with (
        patch("bcbench_core.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch(
            "bcbench_core.agent.copilot.cli.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="warning: slow model\n"),
        ),
    ):
        assert invoke_copilot(prompt="p", model="m", work_dir=tmp_path, timeout=60) == (None, "")

    assert "warning: slow model" in capsys.readouterr().err


def test_copilot_session_args_minimal(tmp_path: Path):
    assert copilot_session_args(tmp_path) == ["--log-level=debug", f"--log-dir={tmp_path.resolve()}"]


def test_copilot_session_args_full_in_cli_order(tmp_path: Path):
    args = copilot_session_args(
        tmp_path / "logs",
        '{"mcpServers":{}}',
        plugin_dirs=[tmp_path / "lsp", tmp_path / "bcquality"],
        granted_dirs=[tmp_path / "bcquality"],
        custom_agent="al-dev",
    )

    assert args == [
        "--log-level=debug",
        f"--log-dir={(tmp_path / 'logs').resolve()}",
        '--additional-mcp-config={"mcpServers":{}}',
        f"--plugin-dir={tmp_path / 'lsp'}",
        f"--plugin-dir={tmp_path / 'bcquality'}",
        f"--add-dir={tmp_path / 'bcquality'}",
        "--agent=al-dev",
    ]
