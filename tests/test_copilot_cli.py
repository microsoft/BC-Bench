import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from bcbench.agent.copilot.agent import run_copilot_agent
from bcbench.agent.copilot.cli import invoke_copilot
from bcbench.agent.shared.contained_process import (
    AgentExecutionPolicy,
    ContainedProcessInfrastructureError,
    ContainedProcessRequest,
    ContainedProcessResult,
    WindowsIdentity,
)
from bcbench.agent.shared.env import agent_subprocess_env
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.types import EvaluationCategory
from tests.conftest import create_dataset_entry


def test_invoke_copilot_default_path_preserves_subprocess_run_parameters(tmp_path: Path):
    env = {"PATH": "agent-path", "TOKEN": "agent-token"}
    with (
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.cli.parse_output", return_value=(None, "done")),
        patch(
            "bcbench.agent.copilot.cli.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='{"type":"result"}\n', stderr=""),
        ) as mock_run,
    ):
        result = invoke_copilot(
            prompt="line one\nline two",
            model="test-model",
            work_dir=tmp_path,
            timeout=60,
            allow_all_tools=True,
            custom_instructions=True,
            extra_args=("--extra",),
            env=env,
            execution_policy=AgentExecutionPolicy(allowlist_environment=True),
        )

    assert result == (None, "done")
    mock_run.assert_called_once_with(
        [
            "copilot",
            "--output-format=json",
            "--allow-all-tools",
            "--disable-builtin-mcps",
            "--model=test-model",
            "--extra",
            "--prompt=line one line two",
        ],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=True,
    )


def test_invoke_copilot_contained_path_constructs_request_and_parses_stdout(tmp_path: Path):
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
    env = {"PATH": "agent-path", "COPILOT_GITHUB_TOKEN": "token"}
    output = '{"type":"result","data":{"content":"finished"}}\n'
    with (
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.cli.parse_output", return_value=(None, "finished")) as mock_parse,
        patch(
            "bcbench.agent.copilot.cli.run_contained_process",
            return_value=ContainedProcessResult(0, output, ""),
        ) as mock_run,
        patch("bcbench.agent.copilot.cli.subprocess.run") as mock_subprocess_run,
    ):
        result = invoke_copilot(
            prompt="do the task",
            model="test-model",
            work_dir=tmp_path,
            timeout=60,
            env=env,
            execution_policy=policy,
        )

    assert result == (None, "finished")
    mock_run.assert_called_once_with(
        ContainedProcessRequest(
            command=(
                "copilot",
                "--output-format=json",
                "--available-tools=none",
                "--disable-builtin-mcps",
                "--no-custom-instructions",
                "--model=test-model",
                "--prompt=do the task",
            ),
            cwd=tmp_path,
            env=env,
            timeout_seconds=60,
            identity=identity,
            python_executable=python_executable,
            worker_path=worker_path,
            worker_sha256="a" * 64,
        )
    )
    mock_subprocess_run.assert_not_called()
    mock_parse.assert_called_once_with([output.strip()], log_transcript=True)


def test_invoke_copilot_contained_nonzero_exit_preserves_stderr(tmp_path: Path):
    with (
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch(
            "bcbench.agent.copilot.cli.run_contained_process",
            return_value=ContainedProcessResult(7, "partial output", "agent stderr"),
        ),
        pytest.raises(subprocess.CalledProcessError) as error,
    ):
        invoke_copilot(
            prompt="do the task",
            model="test-model",
            work_dir=tmp_path,
            timeout=60,
            env={},
            execution_policy=AgentExecutionPolicy(contain_process_tree=True),
        )

    assert error.value.returncode == 7
    assert error.value.stdout == "partial output"
    assert error.value.stderr == "agent stderr"


def test_invoke_copilot_contained_genuine_timeout_remains_timeout_expired(tmp_path: Path):
    timeout = subprocess.TimeoutExpired(("copilot",), 60, output="partial", stderr="timed out")
    with (
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.cli.run_contained_process", side_effect=timeout),
        pytest.raises(subprocess.TimeoutExpired) as error,
    ):
        invoke_copilot(
            prompt="do the task",
            model="test-model",
            work_dir=tmp_path,
            timeout=60,
            env={},
            execution_policy=AgentExecutionPolicy(contain_process_tree=True),
        )

    assert error.value is timeout


def test_invoke_copilot_contained_infrastructure_error_remains_distinguishable(tmp_path: Path):
    infrastructure_error = ContainedProcessInfrastructureError(
        100,
        child_stdout="child stdout",
        child_stderr="child stderr",
        wrapper_stdout="wrapper stdout",
        wrapper_stderr="wrapper stderr",
    )
    with (
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.cli.run_contained_process", side_effect=infrastructure_error),
        pytest.raises(ContainedProcessInfrastructureError) as error,
    ):
        invoke_copilot(
            prompt="do the task",
            model="test-model",
            work_dir=tmp_path,
            timeout=60,
            env={},
            execution_policy=AgentExecutionPolicy(contain_process_tree=True),
        )

    assert error.value is infrastructure_error
    assert not isinstance(error.value, AgentTimeoutError)


def test_invoke_copilot_contained_wrapper_called_process_error_is_infrastructure(tmp_path: Path):
    wrapper_error = subprocess.CalledProcessError(
        17,
        ("pwsh",),
        output=b"wrapper stdout \xff",
        stderr=b"wrapper stderr \xfe",
    )
    with (
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.cli.run_contained_process", side_effect=wrapper_error),
        pytest.raises(ContainedProcessInfrastructureError) as error,
    ):
        invoke_copilot(
            prompt="do the task",
            model="test-model",
            work_dir=tmp_path,
            timeout=60,
            env={},
            execution_policy=AgentExecutionPolicy(contain_process_tree=True),
        )

    assert error.value.__cause__ is wrapper_error
    assert error.value.wrapper_returncode == 17
    assert error.value.wrapper_stdout == "wrapper stdout \ufffd"
    assert error.value.wrapper_stderr == "wrapper stderr \ufffd"
    assert not isinstance(error.value, (AgentError, AgentTimeoutError))


def test_run_copilot_agent_forwards_policy_and_uses_allowlisted_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PATH", "agent-path")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "token")
    monkeypatch.setenv("EVALUATOR_SECRET", "must-not-leak")
    policy = AgentExecutionPolicy(contain_process_tree=True, allowlist_environment=True)
    gateway = Mock(base_url="http://127.0.0.1/mcp")
    with (
        patch("bcbench.agent.copilot.agent.build_prompt", return_value="prompt"),
        patch("bcbench.agent.copilot.agent.build_mcp_config", return_value=(None, None)),
        patch("bcbench.agent.copilot.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.copilot.agent.start_bc_mcp_gateway", return_value=gateway),
        patch("bcbench.agent.copilot.agent.setup_instructions_from_config", return_value=False),
        patch("bcbench.agent.copilot.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.copilot.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.copilot.agent.resolve_config_plugins", return_value=[]),
        patch("bcbench.agent.copilot.agent.invoke_copilot", return_value=(None, "")) as mock_invoke,
    ):
        run_copilot_agent(
            entry=create_dataset_entry(),
            model="test-model",
            category=EvaluationCategory.BUG_FIX,
            repo_path=tmp_path,
            output_dir=tmp_path / "output",
            execution_policy=policy,
        )

    assert mock_invoke.call_args.kwargs["execution_policy"] is policy
    assert mock_invoke.call_args.kwargs["env"] == agent_subprocess_env(
        {"GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": "true"},
        pass_bc_credentials=EvaluationCategory.BUG_FIX.pass_on_bc_container_credentials,
        allowlist=True,
    )
    assert "EVALUATOR_SECRET" not in mock_invoke.call_args.kwargs["env"]
    gateway.stop.assert_called_once_with()


def test_run_copilot_agent_stops_gateway_when_mcp_config_setup_fails(tmp_path: Path):
    gateway = Mock(base_url="http://127.0.0.1/mcp")
    setup_error = RuntimeError("MCP config setup failed")
    with (
        patch("bcbench.agent.copilot.agent.build_prompt", return_value="prompt"),
        patch("bcbench.agent.copilot.agent.start_bc_mcp_gateway", return_value=gateway),
        patch("bcbench.agent.copilot.agent.build_mcp_config", side_effect=setup_error),
        pytest.raises(RuntimeError) as error,
    ):
        run_copilot_agent(
            entry=create_dataset_entry(),
            model="test-model",
            category=EvaluationCategory.BUG_FIX,
            repo_path=tmp_path,
            output_dir=tmp_path / "output",
        )

    assert error.value is setup_error
    gateway.stop.assert_called_once_with()


@pytest.mark.parametrize(
    ("agent_failure", "execution_policy", "expected_error"),
    [
        (
            subprocess.TimeoutExpired(("copilot",), 60, output=b"partial \xff", stderr=b"timed out \xfe"),
            AgentExecutionPolicy(contain_process_tree=True),
            AgentTimeoutError,
        ),
        (
            subprocess.CalledProcessError(3, ("copilot",), output="partial", stderr="agent stderr"),
            None,
            AgentError,
        ),
        (
            ContainedProcessInfrastructureError(
                100,
                child_stdout="child stdout",
                child_stderr="child stderr",
                wrapper_stdout="wrapper stdout",
                wrapper_stderr="wrapper stderr",
            ),
            AgentExecutionPolicy(contain_process_tree=True),
            ContainedProcessInfrastructureError,
        ),
    ],
)
def test_run_copilot_agent_preserves_error_class_and_stops_gateway(
    tmp_path: Path,
    agent_failure: Exception,
    execution_policy: AgentExecutionPolicy | None,
    expected_error: type[Exception],
):
    gateway = Mock(base_url="http://127.0.0.1/mcp")
    with (
        patch("bcbench.agent.copilot.agent.build_prompt", return_value="prompt"),
        patch("bcbench.agent.copilot.agent.build_mcp_config", return_value=(None, None)),
        patch("bcbench.agent.copilot.agent.build_al_lsp_plugin", return_value=None),
        patch("bcbench.agent.copilot.agent.start_bc_mcp_gateway", return_value=gateway),
        patch("bcbench.agent.copilot.agent.setup_instructions_from_config", return_value=False),
        patch("bcbench.agent.copilot.agent.setup_agent_skills", return_value=False),
        patch("bcbench.agent.copilot.agent.setup_custom_agent", return_value=None),
        patch("bcbench.agent.copilot.agent.resolve_config_plugins", return_value=[]),
        patch("bcbench.agent.copilot.agent.invoke_copilot", side_effect=agent_failure),
        pytest.raises(expected_error) as error,
    ):
        run_copilot_agent(
            entry=create_dataset_entry(),
            model="test-model",
            category=EvaluationCategory.BUG_FIX,
            repo_path=tmp_path,
            output_dir=tmp_path / "output",
            execution_policy=execution_policy,
        )

    if isinstance(agent_failure, subprocess.CalledProcessError):
        assert "agent stderr" in str(error.value)
    if isinstance(agent_failure, subprocess.TimeoutExpired):
        assert error.value.metrics.execution_time > 0
        assert error.value.config is not None
        assert error.value.stdout == "partial \ufffd"
        assert error.value.stderr == "timed out \ufffd"
        assert error.value.__cause__ is agent_failure
    gateway.stop.assert_called_once_with()
