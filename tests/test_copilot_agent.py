import subprocess
from pathlib import Path
from unittest.mock import patch

from bcbench.agent.copilot.agent import run_copilot_agent
from bcbench.types import EvaluationCategory
from tests.conftest import create_dataset_entry


def test_copilot_does_not_enable_memory_or_unrestricted_urls(tmp_path: Path):
    repo_path = tmp_path / "repo"
    output_dir = tmp_path / "output"
    repo_path.mkdir()
    output_dir.mkdir()
    tool_log_path = output_dir / "tool_usage.jsonl"

    with (
        patch("bcbench.agent.copilot.agent.find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.agent.build_prompt", return_value="line one\nline two"),
        patch("bcbench.agent.copilot.agent.build_mcp_config", return_value=(None, None)),
        patch("bcbench.agent.copilot.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.copilot.agent.setup_instructions_from_config", return_value=False),
        patch("bcbench.agent.copilot.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.copilot.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.copilot.agent.setup_hooks", return_value=tool_log_path),
        patch("bcbench.agent.copilot.agent.resolve_config_plugins", return_value=[]),
        patch("bcbench.agent.copilot.agent.parse_output", return_value=(None, None)) as mock_parse_output,
        patch("bcbench.agent.copilot.agent.parse_tool_usage_from_hooks", return_value=None),
        patch(
            "bcbench.agent.copilot.agent.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=b'{"type":"result"}\n', stderr=b""),
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
        "--model=copilot-test-model",
        "--log-level=debug",
        f"--log-dir={output_dir.resolve()}",
        "--prompt=line one line two",
        "--no-custom-instructions",
    ]
    assert mock_run.call_args.kwargs["capture_output"] is True
    mock_parse_output.assert_called_once_with(['{"type":"result"}'])
