import subprocess
from pathlib import Path
from unittest.mock import patch

from bcbench.agent.copilot.agent import run_copilot_agent
from bcbench.agent.copilot.cli import invoke_copilot
from bcbench.types import EvaluationCategory
from tests.conftest import create_dataset_entry


def test_invoke_copilot_defaults_to_none_tool_argument_and_no_custom_instructions(tmp_path: Path):
    with (
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.cli.parse_output", return_value=(None, None)),
        patch(
            "bcbench.agent.copilot.cli.subprocess.run",
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
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.cli.parse_output", return_value=(None, None)),
        patch(
            "bcbench.agent.copilot.cli.subprocess.run",
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
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch(
            "bcbench.agent.copilot.cli.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=output, stderr=""),
        ),
    ):
        invoke_copilot(prompt="do the task", model="test-model", work_dir=tmp_path, timeout=60)

    assert "Copilot: working" in caplog.messages
    assert output not in caplog.text


def test_copilot_does_not_enable_hooks_memory_or_unrestricted_urls(tmp_path: Path, monkeypatch):
    repo_path = tmp_path / "repo"
    output_dir = tmp_path / "output"
    repo_path.mkdir()
    output_dir.mkdir()
    monkeypatch.delenv("GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS", raising=False)
    monkeypatch.setenv("BC_SERVER_USERNAME", "admin")
    monkeypatch.setenv("BC_SERVER_PASSWORD", "secret")

    with (
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.agent.build_prompt", return_value="line one\nline two"),
        patch("bcbench.agent.copilot.agent.build_mcp_config", return_value=(None, None)),
        patch("bcbench.agent.copilot.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.copilot.agent.setup_instructions_from_config", return_value=False),
        patch("bcbench.agent.copilot.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.copilot.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.copilot.agent.resolve_config_plugins", return_value=[]),
        patch("bcbench.agent.copilot.cli.parse_output", return_value=(None, None)) as mock_parse_output,
        patch(
            "bcbench.agent.copilot.cli.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='{"type":"result"}\n', stderr=""),
        ) as mock_run,
    ):
        run_copilot_agent(
            entry=create_dataset_entry(),
            model="copilot-test-model",
            category=EvaluationCategory.BUG_FIX,
            repo_path=repo_path,
            output_dir=output_dir,
        )

    assert mock_run.call_args.args[0] == [
        "copilot",
        "--output-format=json",
        "--allow-all-tools",
        "--disable-builtin-mcps",
        "--no-custom-instructions",
        "--model=copilot-test-model",
        "--log-level=debug",
        f"--log-dir={output_dir.resolve()}",
        "--prompt=line one line two",
    ]
    assert mock_run.call_args.kwargs["capture_output"] is True
    assert mock_run.call_args.kwargs["text"] is True
    assert "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS" not in mock_run.call_args.kwargs["env"]
    assert mock_run.call_args.kwargs["env"]["BC_SERVER_USERNAME"] == "admin"
    assert mock_run.call_args.kwargs["env"]["BC_SERVER_PASSWORD"] == "secret"
    mock_parse_output.assert_called_once_with(['{"type":"result"}'], log_transcript=True)
