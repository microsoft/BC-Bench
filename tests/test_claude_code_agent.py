import os
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.claude import agent as claude_agent
from bcbench.agent.claude.agent import run_claude_code
from bcbench.types import AgentRuntimeConfig, ContainerConfig, EvaluationCategory
from tests.conftest import create_dataset_entry


@pytest.mark.parametrize(
    ("al_mcp", "bc_mcp", "al_lsp", "expected_tool_timeout"),
    [
        pytest.param(None, False, False, "180000", id="no-runtime"),
        pytest.param(False, False, False, "180000", id="no-mcp"),
        pytest.param(True, False, False, "1234000", id="al-mcp"),
        pytest.param(False, True, False, "180000", id="bc-mcp"),
        pytest.param(True, True, False, "1234000", id="both-mcp"),
        pytest.param(False, False, True, "180000", id="lsp-only"),
    ],
)
def test_claude_code_excludes_user_settings_and_auto_memory(tmp_path: Path, monkeypatch, al_mcp, bc_mcp, al_lsp, expected_tool_timeout):
    repo_path = tmp_path / "repo"
    output_dir = tmp_path / "output"
    repo_path.mkdir()
    output_dir.mkdir()
    monkeypatch.setenv("BCBENCH_TEST_SENTINEL", "preserved")
    monkeypatch.setenv("BC_SERVER_USERNAME", "admin")
    monkeypatch.setenv("BC_SERVER_PASSWORD", "secret")
    monkeypatch.delenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", raising=False)
    config = claude_agent._config
    monkeypatch.setattr(claude_agent, "_config", replace(config, timeout=replace(config.timeout, build_baseapp=1234)))
    runtime = (
        None
        if al_mcp is None
        else AgentRuntimeConfig(
            container=ContainerConfig("test", "admin", "secret", "CRONUS", mcp_url="http://localhost/mcp"),
            al_mcp=al_mcp,
            bc_mcp=bc_mcp,
            al_lsp=al_lsp,
        )
    )
    with (
        patch("bcbench.agent.claude.agent.shutil.which", return_value="claude"),
        patch("bcbench.agent.claude.agent.build_prompt", return_value="line one\nline two"),
        patch("bcbench.agent.claude.agent.build_mcp_config", return_value=(None, None)),
        patch("bcbench.agent.claude.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.claude.agent.start_bc_mcp_gateway", return_value=None),
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
            runtime=runtime,
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
    assert env["BC_SERVER_USERNAME"] == "admin"
    assert env["BC_SERVER_PASSWORD"] == "secret"
    assert env["MCP_TIMEOUT"] == "180000"
    assert env["MCP_TOOL_TIMEOUT"] == expected_tool_timeout
    assert mock_run.call_args.kwargs["timeout"] == config.timeout.agent_execution
    assert "CLAUDE_CODE_DISABLE_AUTO_MEMORY" not in os.environ


def test_bug_fix_publish_failures_are_terminal_in_both_instruction_copies():
    instructions = Path(__file__).resolve().parents[1] / "src" / "bcbench" / "agent" / "shared" / "instructions"
    texts = [(instructions / repo / "agents" / "fix-bug" / "troubleshooting.md").read_text() for repo in ("microsoftInternal-NAV", "microsoft-BCApps")]
    assert texts[0] == texts[1]
    timeout_section = texts[0].split("## Publish timed out\n", 1)[1].split("\n---", 1)[0]
    failure_section = texts[0].split("## Publish failed\n", 1)[1].split("\n---", 1)[0]
    assert "Do not retry the publish" in timeout_section
    assert "does not prove" in timeout_section
    assert "terminal infrastructure" in " ".join(failure_section.split())
    assert "Retry at most once" not in failure_section
