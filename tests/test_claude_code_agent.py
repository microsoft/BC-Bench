import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from bcbench.agent.claude.agent import run_claude_code
from bcbench.types import EvaluationCategory
from tests.conftest import create_dataset_entry


def test_claude_code_excludes_user_settings_and_auto_memory(tmp_path: Path, monkeypatch):
    repo_path = tmp_path / "repo"
    output_dir = tmp_path / "output"
    repo_path.mkdir()
    output_dir.mkdir()
    monkeypatch.setenv("BCBENCH_TEST_SENTINEL", "preserved")
    monkeypatch.delenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", raising=False)

    with (
        patch("bcbench.agent.claude.agent.shutil.which", return_value="claude"),
        patch("bcbench.agent.claude.agent.build_prompt", return_value="line one\nline two"),
        patch("bcbench.agent.claude.agent.build_mcp_config", return_value=(None, None)),
        patch("bcbench.agent.claude.agent.build_al_lsp_plugin", return_value=None),
        patch(
            "bcbench.agent.claude.agent.setup_instructions_from_config",
            return_value=False,
        ),
        patch("bcbench.agent.claude.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.claude.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.claude.agent.resolve_config_plugins", return_value=[]),
        patch(
            "bcbench.agent.claude.agent.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=b"{}\n", stderr=b""),
        ) as mock_run,
    ):
        run_claude_code(
            entry=create_dataset_entry(),
            model="claude-test-model",
            category=EvaluationCategory.BUG_FIX,
            repo_path=repo_path,
            output_dir=output_dir,
        )

    assert mock_run.call_args.args[0] == [
        "claude",
        "--output-format=stream-json",
        "--verbose",
        "--strict-mcp-config",
        "--setting-sources=project,local",
        "--model=claude-test-model",
        "--permission-mode=bypassPermissions",
        "--disallowedTools",
        "WebFetch",
        "Bash(curl *)",
        "Bash(wget *)",
        "--print",
        "line one line two",
    ]
    env = mock_run.call_args.kwargs["env"]
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert env["BCBENCH_TEST_SENTINEL"] == "preserved"
    assert "CLAUDE_CODE_DISABLE_AUTO_MEMORY" not in os.environ
