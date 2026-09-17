import json
import logging
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from bcbench.agent.claude import agent as claude_agent
from bcbench.agent.claude.agent import run_claude_code
from bcbench.agent.shared.contained_process import (
    AgentExecutionPolicy,
    ContainedProcessInfrastructureError,
    ContainedProcessRequest,
    ContainedProcessResult,
    WindowsIdentity,
)
from bcbench.agent.shared.env import agent_subprocess_env
from bcbench.exceptions import AgentError, AgentTimeoutError
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


def test_claude_code_debug_output_excludes_credentials_prompt_and_raw_output(tmp_path: Path, caplog, capsys):
    secret = "distinctive-claude-agent-secret"
    mcp_config = json.dumps(
        {
            "mcpServers": {
                "altool": {
                    "command": "al",
                    "env": {"BC_SERVER_PASSWORD": secret},
                }
            }
        }
    )
    caplog.set_level(logging.DEBUG, logger="bcbench.agent.claude.agent")
    with (
        patch("bcbench.agent.claude.agent.shutil.which", return_value="claude"),
        patch("bcbench.agent.claude.agent.build_prompt", return_value=f"prompt containing {secret}"),
        patch("bcbench.agent.claude.agent.build_mcp_config", return_value=(mcp_config, ["altool"])),
        patch("bcbench.agent.claude.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.claude.agent.start_bc_mcp_gateway", return_value=None),
        patch("bcbench.agent.claude.agent.setup_instructions_from_config", return_value=False),
        patch("bcbench.agent.claude.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.claude.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.claude.agent.resolve_config_plugins", return_value=[]),
        patch(
            "bcbench.agent.claude.agent.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f'{{"type":"result","credential":"{secret}"}}\n'.encode(),
                stderr=b"",
            ),
        ),
        patch("bcbench.agent.claude.agent.parse_stream_output", return_value=(None, "done")),
    ):
        run_claude_code(
            entry=create_dataset_entry(),
            model="safe-claude-model",
            category=EvaluationCategory.BUG_FIX,
            repo_path=tmp_path,
            output_dir=tmp_path / "output",
        )

    captured = capsys.readouterr()
    combined_output = caplog.text + captured.out + captured.err
    assert secret not in combined_output
    assert "BC_SERVER_PASSWORD" not in combined_output
    assert "safe-claude-model" in caplog.text
    assert "altool" in caplog.text


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


def test_claude_code_contained_path_constructs_request_and_parses_stdout(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PATH", "agent-path")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "token")
    monkeypatch.setenv("EVALUATOR_SECRET", "must-not-leak")
    identity = WindowsIdentity("restricted", "secret", "DOMAIN")
    python_executable = tmp_path / "python.exe"
    worker_path = tmp_path / "agent-tools" / "contained_process_worker.py"
    policy = AgentExecutionPolicy(
        contain_process_tree=True,
        restricted_identity=identity,
        allowlist_environment=True,
        python_executable=python_executable,
        worker_path=worker_path,
        worker_sha256="a" * 64,
    )
    gateway = Mock(base_url="http://127.0.0.1/mcp")
    output = '{"type":"result","result":"finished"}\n'
    with (
        patch("bcbench.agent.claude.agent.shutil.which", return_value="claude"),
        patch("bcbench.agent.claude.agent.build_prompt", return_value="line one\nline two"),
        patch("bcbench.agent.claude.agent.build_mcp_config", return_value=(None, None)),
        patch("bcbench.agent.claude.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.claude.agent.start_bc_mcp_gateway", return_value=gateway),
        patch("bcbench.agent.claude.agent.setup_instructions_from_config", return_value=False),
        patch("bcbench.agent.claude.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.claude.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.claude.agent.resolve_config_plugins", return_value=[]),
        patch(
            "bcbench.agent.claude.agent.run_contained_process",
            return_value=ContainedProcessResult(0, output, ""),
        ) as mock_run,
        patch("bcbench.agent.claude.agent.parse_stream_output", return_value=(None, "finished")) as mock_parse,
        patch("bcbench.agent.claude.agent.subprocess.run") as mock_subprocess_run,
    ):
        result = run_claude_code(
            entry=create_dataset_entry(),
            model="claude-test-model",
            category=EvaluationCategory.BUG_FIX,
            repo_path=tmp_path,
            output_dir=tmp_path / "output",
            execution_policy=policy,
        )

    command = (
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
    )
    expected_env = agent_subprocess_env(
        {
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "MCP_TIMEOUT": "180000",
            "MCP_TOOL_TIMEOUT": "180000",
        },
        pass_bc_credentials=EvaluationCategory.BUG_FIX.pass_on_bc_container_credentials,
        allowlist=True,
    )
    mock_run.assert_called_once_with(
        ContainedProcessRequest(
            command=command,
            cwd=tmp_path,
            env=expected_env,
            timeout_seconds=claude_agent._config.timeout.agent_execution,
            identity=identity,
            python_executable=python_executable,
            worker_path=worker_path,
            worker_sha256="a" * 64,
        )
    )
    mock_subprocess_run.assert_not_called()
    mock_parse.assert_called_once_with([output.strip()], log_transcript=False)
    assert result[0] is None
    assert "EVALUATOR_SECRET" not in expected_env
    gateway.stop.assert_called_once_with()


def test_claude_code_contained_path_does_not_log_credential_transcript(tmp_path: Path, caplog):
    agent_bc_password = "agent-bc-password-value"
    agent_os_password = "agent-os-password-value"
    token = "agent-token-value"
    assistant_content = f"Credentials: {agent_bc_password} {agent_os_password} {token}"
    final_response = "Completed safely."
    output = "\n".join(
        [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": assistant_content},
                            {"type": "tool_use", "name": "Bash", "input": {}},
                        ]
                    },
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "duration_ms": 1500,
                    "duration_api_ms": 750,
                    "num_turns": 2,
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "result": final_response,
                }
            ),
        ]
    )
    policy = AgentExecutionPolicy(contain_process_tree=True, allowlist_environment=True)
    caplog.set_level(logging.INFO)

    with (
        patch("bcbench.agent.claude.agent.shutil.which", return_value="claude"),
        patch("bcbench.agent.claude.agent.build_prompt", return_value="prompt"),
        patch("bcbench.agent.claude.agent.build_mcp_config", return_value=(None, None)),
        patch("bcbench.agent.claude.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.claude.agent.start_bc_mcp_gateway", return_value=None),
        patch("bcbench.agent.claude.agent.setup_instructions_from_config", return_value=False),
        patch("bcbench.agent.claude.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.claude.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.claude.agent.resolve_config_plugins", return_value=[]),
        patch(
            "bcbench.agent.claude.agent.run_contained_process",
            return_value=ContainedProcessResult(0, output, ""),
        ),
    ):
        metrics, _ = run_claude_code(
            entry=create_dataset_entry(),
            model="test-model",
            category=EvaluationCategory.BUG_FIX,
            repo_path=tmp_path,
            output_dir=tmp_path / "output",
            execution_policy=policy,
        )

    assert metrics is not None
    assert metrics.execution_time == 1.5
    assert metrics.llm_duration == 0.75
    assert metrics.turn_count == 2
    assert metrics.prompt_tokens == 10
    assert metrics.completion_tokens == 5
    assert metrics.tool_usage == {"Bash": 1}
    assert agent_bc_password not in caplog.text
    assert agent_os_password not in caplog.text
    assert token not in caplog.text


def test_claude_code_default_path_logs_transcript(tmp_path: Path, caplog):
    assistant_content = "Ordinary Claude transcript remains visible."
    output = json.dumps(
        {
            "type": "result",
            "duration_ms": 1000,
            "result": assistant_content,
        }
    ).encode()
    caplog.set_level(logging.INFO)

    with (
        patch("bcbench.agent.claude.agent.shutil.which", return_value="claude"),
        patch("bcbench.agent.claude.agent.build_prompt", return_value="prompt"),
        patch("bcbench.agent.claude.agent.build_mcp_config", return_value=(None, None)),
        patch("bcbench.agent.claude.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.claude.agent.start_bc_mcp_gateway", return_value=None),
        patch("bcbench.agent.claude.agent.setup_instructions_from_config", return_value=False),
        patch("bcbench.agent.claude.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.claude.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.claude.agent.resolve_config_plugins", return_value=[]),
        patch(
            "bcbench.agent.claude.agent.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=output, stderr=b""),
        ),
    ):
        metrics, _ = run_claude_code(
            entry=create_dataset_entry(),
            model="test-model",
            category=EvaluationCategory.BUG_FIX,
            repo_path=tmp_path,
            output_dir=tmp_path / "output",
        )

    assert metrics is not None
    assert metrics.execution_time == 1.0
    assert f"Claude Code: {assistant_content}" in caplog.messages


def test_claude_code_stops_gateway_when_mcp_config_setup_fails(tmp_path: Path):
    gateway = Mock(base_url="http://127.0.0.1/mcp")
    setup_error = RuntimeError("MCP config setup failed")
    with (
        patch("bcbench.agent.claude.agent.shutil.which", return_value="claude"),
        patch("bcbench.agent.claude.agent.build_prompt", return_value="prompt"),
        patch("bcbench.agent.claude.agent.start_bc_mcp_gateway", return_value=gateway),
        patch("bcbench.agent.claude.agent.build_mcp_config", side_effect=setup_error),
        pytest.raises(RuntimeError) as error,
    ):
        run_claude_code(
            entry=create_dataset_entry(),
            model="claude-test-model",
            category=EvaluationCategory.BUG_FIX,
            repo_path=tmp_path,
            output_dir=tmp_path / "output",
        )

    assert error.value is setup_error
    gateway.stop.assert_called_once_with()


@pytest.mark.parametrize(
    ("contained_result", "contained_error", "expected_error"),
    [
        (ContainedProcessResult(3, "partial", "agent stderr"), None, AgentError),
        (
            None,
            subprocess.TimeoutExpired(("claude",), 60, output=b"partial \xff", stderr=b"timed out \xfe"),
            AgentTimeoutError,
        ),
        (
            None,
            subprocess.CalledProcessError(
                17,
                ("pwsh",),
                output=b"wrapper stdout \xff",
                stderr=b"wrapper stderr \xfe",
            ),
            ContainedProcessInfrastructureError,
        ),
        (
            None,
            ContainedProcessInfrastructureError(
                100,
                child_stdout="child stdout",
                child_stderr="child stderr",
                wrapper_stdout="wrapper stdout",
                wrapper_stderr="wrapper stderr",
            ),
            ContainedProcessInfrastructureError,
        ),
    ],
)
def test_claude_code_contained_errors_preserve_class_and_stop_gateway(
    tmp_path: Path,
    contained_result: ContainedProcessResult | None,
    contained_error: Exception | None,
    expected_error: type[Exception],
):
    gateway = Mock(base_url="http://127.0.0.1/mcp")
    with (
        patch("bcbench.agent.claude.agent.shutil.which", return_value="claude"),
        patch("bcbench.agent.claude.agent.build_prompt", return_value="prompt"),
        patch("bcbench.agent.claude.agent.build_mcp_config", return_value=(None, None)),
        patch("bcbench.agent.claude.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.claude.agent.start_bc_mcp_gateway", return_value=gateway),
        patch("bcbench.agent.claude.agent.setup_instructions_from_config", return_value=False),
        patch("bcbench.agent.claude.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.claude.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.claude.agent.resolve_config_plugins", return_value=[]),
        patch(
            "bcbench.agent.claude.agent.run_contained_process",
            return_value=contained_result,
            side_effect=contained_error,
        ),
        pytest.raises(expected_error) as error,
    ):
        run_claude_code(
            entry=create_dataset_entry(),
            model="claude-test-model",
            category=EvaluationCategory.BUG_FIX,
            repo_path=tmp_path,
            output_dir=tmp_path / "output",
            execution_policy=AgentExecutionPolicy(contain_process_tree=True),
        )

    if expected_error is AgentError:
        assert "status 3" in str(error.value)
        assert "agent stderr" not in str(error.value)
    if expected_error is AgentTimeoutError:
        assert error.value.metrics.execution_time > 0
        assert error.value.config is not None
        assert error.value.stdout == "partial \ufffd"
        assert error.value.stderr == "timed out \ufffd"
        assert error.value.__cause__ is None
    if expected_error is ContainedProcessInfrastructureError:
        if isinstance(contained_error, subprocess.CalledProcessError):
            assert error.value.__cause__ is contained_error
            assert error.value.wrapper_returncode == 17
            assert error.value.wrapper_stdout == "wrapper stdout \ufffd"
            assert error.value.wrapper_stderr == "wrapper stderr \ufffd"
        else:
            assert error.value is contained_error
        assert not isinstance(error.value, AgentTimeoutError)
    gateway.stop.assert_called_once_with()


def test_claude_code_default_called_process_error_remains_agent_error(tmp_path: Path):
    failure = subprocess.CalledProcessError(3, ("claude",), output=b"partial", stderr=b"agent stderr")
    with (
        patch("bcbench.agent.claude.agent.shutil.which", return_value="claude"),
        patch("bcbench.agent.claude.agent.build_prompt", return_value="prompt"),
        patch("bcbench.agent.claude.agent.build_mcp_config", return_value=(None, None)),
        patch("bcbench.agent.claude.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.claude.agent.start_bc_mcp_gateway", return_value=None),
        patch("bcbench.agent.claude.agent.setup_instructions_from_config", return_value=False),
        patch("bcbench.agent.claude.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.claude.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.claude.agent.resolve_config_plugins", return_value=[]),
        patch("bcbench.agent.claude.agent.subprocess.run", side_effect=failure),
        pytest.raises(AgentError) as error,
    ):
        run_claude_code(
            entry=create_dataset_entry(),
            model="claude-test-model",
            category=EvaluationCategory.BUG_FIX,
            repo_path=tmp_path,
            output_dir=tmp_path / "output",
        )

    assert error.value.__cause__ is None
    assert "status 3" in str(error.value)
    assert "agent stderr" not in str(error.value)


def test_claude_code_failure_excludes_credentials_from_exception_and_logs(tmp_path: Path, caplog, capsys):
    secret = "distinctive-claude-failure-secret"
    mcp_config = json.dumps({"mcpServers": {"altool": {"env": {"BC_SERVER_PASSWORD": secret}}}})
    failure = subprocess.CalledProcessError(
        3,
        ("claude", f"--mcp-config={mcp_config}", secret),
        stderr=f"agent failure containing {secret}",
    )
    caplog.set_level(logging.DEBUG, logger="bcbench.agent.claude.agent")
    with (
        patch("bcbench.agent.claude.agent.shutil.which", return_value="claude"),
        patch("bcbench.agent.claude.agent.build_prompt", return_value=f"prompt containing {secret}"),
        patch("bcbench.agent.claude.agent.build_mcp_config", return_value=(mcp_config, ["altool"])),
        patch("bcbench.agent.claude.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.claude.agent.start_bc_mcp_gateway", return_value=None),
        patch("bcbench.agent.claude.agent.setup_instructions_from_config", return_value=False),
        patch("bcbench.agent.claude.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.claude.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.claude.agent.resolve_config_plugins", return_value=[]),
        patch("bcbench.agent.claude.agent.subprocess.run", side_effect=failure),
        pytest.raises(AgentError) as error,
    ):
        run_claude_code(
            entry=create_dataset_entry(),
            model="safe-claude-model",
            category=EvaluationCategory.BUG_FIX,
            repo_path=tmp_path,
            output_dir=tmp_path / "output",
        )

    captured = capsys.readouterr()
    assert secret not in str(error.value)
    assert secret not in caplog.text + captured.out + captured.err
    assert "BC_SERVER_PASSWORD" not in caplog.text
