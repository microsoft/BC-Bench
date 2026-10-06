import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.copilot.agent import run_copilot_agent
from bcbench.types import EvaluationCategory, PluginConfig
from tests.conftest import create_dataset_entry


def test_copilot_does_not_enable_hooks_memory_or_unrestricted_urls(tmp_path: Path, monkeypatch):
    repo_path = tmp_path / "repo"
    output_dir = tmp_path / "output"
    repo_path.mkdir()
    output_dir.mkdir()
    monkeypatch.delenv("GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS", raising=False)
    monkeypatch.setenv("BC_SERVER_USERNAME", "admin")
    monkeypatch.setenv("BC_SERVER_PASSWORD", "secret")
    with (
        patch("bcbench_core.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.agent.build_prompt", return_value="line one\nline two"),
        patch("bcbench.agent.copilot.agent.build_mcp_config", return_value=(None, None)),
        patch("bcbench.agent.copilot.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.copilot.agent.setup_instructions_from_config", return_value=False),
        patch("bcbench.agent.copilot.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.copilot.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.copilot.agent.resolve_config_plugins", return_value=[]),
        patch("bcbench_core.agent.copilot.cli.parse_output", return_value=(None, None)) as mock_parse_output,
        patch(
            "bcbench_core.agent.copilot.cli.subprocess.run",
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


@pytest.mark.parametrize("lsp_enabled", [False, True])
def test_copilot_session_options_preserve_plugin_order_and_explicit_directory_grants(tmp_path: Path, lsp_enabled: bool):
    repo_path = tmp_path / "repo"
    output_dir = tmp_path / "output"
    repo_path.mkdir()
    output_dir.mkdir()
    lsp_dir = tmp_path / "lsp" if lsp_enabled else None
    plugin_dir = tmp_path / "plugin"
    granted_dir = tmp_path / "granted plugin"
    plugins = [
        (PluginConfig(name="probe", source="local", path=str(plugin_dir), enabled=True), plugin_dir),
        (PluginConfig(name="granted", source="local", path=str(granted_dir), enabled=True, grant_dir_access=True), granted_dir),
    ]
    mcp_config_json = '{"mcpServers":{"probe":{"command":"probe-mcp"}}}'
    with (
        patch("bcbench_core.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.agent.build_prompt", return_value="do the task"),
        patch("bcbench.agent.copilot.agent.build_mcp_config", return_value=(mcp_config_json, ["probe"])),
        patch("bcbench.agent.copilot.agent.build_al_lsp_plugin", return_value=lsp_dir),
        patch("bcbench.agent.copilot.agent.setup_instructions_from_config", return_value=True),
        patch("bcbench.agent.copilot.agent.setup_agent_skills", return_value=True),
        patch("bcbench.agent.copilot.agent.setup_custom_agent", return_value="al-dev"),
        patch("bcbench.agent.copilot.agent.resolve_config_plugins", return_value=plugins),
        patch("bcbench_core.agent.copilot.cli.parse_output", return_value=(None, None)),
        patch(
            "bcbench_core.agent.copilot.cli.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='{"type":"result"}\n', stderr=""),
        ) as mock_run,
    ):
        _, config = run_copilot_agent(
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
        "--model=copilot-test-model",
        "--log-level=debug",
        f"--log-dir={output_dir.resolve()}",
        f"--additional-mcp-config={mcp_config_json}",
        *([f"--plugin-dir={lsp_dir}"] if lsp_dir is not None else []),
        f"--plugin-dir={plugin_dir}",
        f"--plugin-dir={granted_dir}",
        f"--add-dir={granted_dir}",
        "--agent=al-dev",
        "--prompt=do the task",
    ]
    assert config.mcp_servers == ["probe"]
    assert config.al_lsp_enabled is lsp_enabled
    assert config.custom_instructions is True
    assert config.skills_enabled is True
    assert config.custom_agent == "al-dev"
    assert config.plugins == ["probe@local", "granted@local"]
