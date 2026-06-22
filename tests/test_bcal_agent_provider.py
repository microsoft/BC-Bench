"""Tests for the bcal agent's LLM backend configuration."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bcbench.agent.bcal import BCalBackendConfig
from bcbench.agent.bcal import agent as bcal_agent
from bcbench.exceptions import AgentError
from bcbench.types import BCalLLMBackend
from tests.conftest import create_nl2al_entry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    project_name = "JobBudgetVsActualReport"
    (tmp_path / project_name / ".alpackages").mkdir(parents=True)
    return tmp_path


class TestCliArgs:
    def test_azure_openai_includes_endpoint_and_deployment(self):
        args = BCalBackendConfig(backend=BCalLLMBackend.AZURE_OPENAI, endpoint="https://aoai.example/", deployment="gpt-5.2").cli_args()
        assert "--endpoint=https://aoai.example/" in args
        assert "--deployment=gpt-5.2" in args
        assert not any(a.startswith("--llm-backend=") for a in args)

    def test_azure_openai_requires_endpoint(self):
        with pytest.raises(AgentError):
            BCalBackendConfig(backend=BCalLLMBackend.AZURE_OPENAI, deployment="gpt-5.2").cli_args()

    def test_azure_openai_requires_deployment(self):
        with pytest.raises(AgentError):
            BCalBackendConfig(backend=BCalLLMBackend.AZURE_OPENAI, endpoint="https://aoai.example/").cli_args()

    def test_string_inputs_are_stripped(self):
        config = BCalBackendConfig(backend=BCalLLMBackend.AZURE_OPENAI, endpoint=" https://aoai.example/ ", deployment=" gpt-5.2 ")
        assert config.cli_args() == ["--endpoint=https://aoai.example/", "--deployment=gpt-5.2"]

    def test_external_command_includes_command_and_model(self):
        args = BCalBackendConfig(backend=BCalLLMBackend.EXTERNAL_COMMAND, command="python bridge.py", model="gpt-5").cli_args()
        assert "--llm-backend=external-command" in args
        assert "--llm-command=python bridge.py" in args
        assert "--deployment=gpt-5" in args
        assert not any(a.startswith("--endpoint=") for a in args)

    def test_external_command_requires_command(self):
        with pytest.raises(AgentError):
            BCalBackendConfig(backend=BCalLLMBackend.EXTERNAL_COMMAND, model="gpt-5").cli_args()

    def test_whitespace_only_required_values_are_missing(self):
        with pytest.raises(AgentError):
            BCalBackendConfig(backend=BCalLLMBackend.EXTERNAL_COMMAND, command="   ").cli_args()

    def test_external_command_model_is_optional(self):
        args = BCalBackendConfig(backend=BCalLLMBackend.EXTERNAL_COMMAND, command="python bridge.py").cli_args()
        assert "--llm-backend=external-command" in args
        assert "--llm-command=python bridge.py" in args
        assert not any(a.startswith("--deployment=") for a in args)


class TestModelLabel:
    def test_azure_openai_uses_deployment(self):
        config = BCalBackendConfig(backend=BCalLLMBackend.AZURE_OPENAI, endpoint="https://aoai.example/", deployment=" gpt-5.2 ")
        assert config.model_label() == "gpt-5.2"

    def test_external_command_uses_model_when_present(self):
        config = BCalBackendConfig(backend=BCalLLMBackend.EXTERNAL_COMMAND, command="python bridge.py", model=" gpt-5 ")
        assert config.model_label() == "gpt-5"

    def test_external_command_without_model_uses_backend_name(self):
        config = BCalBackendConfig(backend=BCalLLMBackend.EXTERNAL_COMMAND, command="python bridge.py")
        assert config.model_label() == "external-command"


class TestRunBcalAgentAzureOpenAI:
    def test_passes_aoai_endpoint_to_subprocess(self, workspace: Path):
        entry = create_nl2al_entry()

        captured: dict[str, list[str]] = {}

        def fake_run(args: list[str], **_: object) -> MagicMock:
            captured["args"] = args
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
        ):
            metrics, _ = bcal_agent.run_bcal_agent(
                entry=entry,
                repo_path=workspace,
                backend_config=BCalBackendConfig(
                    backend=BCalLLMBackend.AZURE_OPENAI,
                    endpoint="https://aoai.example/",
                    deployment="gpt-5.2",
                ),
            )

        assert metrics is not None
        assert "--endpoint=https://aoai.example/" in captured["args"]
        assert "--deployment=gpt-5.2" in captured["args"]
        assert not any(a.startswith("--llm-backend=") for a in captured["args"])


class TestRunBcalAgentExternalCommand:
    def test_passes_external_command_backend_to_bcal(self, workspace: Path):
        entry = create_nl2al_entry()
        captured: dict[str, list[str]] = {}

        def fake_run(args: list[str], **_: object) -> MagicMock:
            captured["args"] = args
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
        ):
            metrics, _ = bcal_agent.run_bcal_agent(
                entry=entry,
                repo_path=workspace,
                backend_config=BCalBackendConfig(
                    backend=BCalLLMBackend.EXTERNAL_COMMAND,
                    command="python bridge.py",
                    model="gpt-5",
                ),
            )

        assert metrics is not None
        args = captured["args"]
        assert "--deployment=gpt-5" in args
        assert "--llm-backend=external-command" in args
        assert "--llm-command=python bridge.py" in args
        assert not any(a.startswith("--endpoint=") for a in args)
        assert not any(a.startswith("--capi-") for a in args)

    def test_external_command_requires_command(self, workspace: Path):
        entry = create_nl2al_entry()

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            pytest.raises(AgentError),
        ):
            bcal_agent.run_bcal_agent(entry=entry, repo_path=workspace, backend_config=BCalBackendConfig(backend=BCalLLMBackend.EXTERNAL_COMMAND))

    def test_external_command_model_is_optional(self, workspace: Path):
        entry = create_nl2al_entry()
        captured: dict[str, list[str]] = {}

        def fake_run(args: list[str], **_: object) -> MagicMock:
            captured["args"] = args
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
        ):
            bcal_agent.run_bcal_agent(
                entry=entry,
                repo_path=workspace,
                backend_config=BCalBackendConfig(
                    backend=BCalLLMBackend.EXTERNAL_COMMAND,
                    command="python bridge.py",
                ),
            )

        assert "--llm-backend=external-command" in captured["args"]
        assert "--llm-command=python bridge.py" in captured["args"]
        assert not any(a.startswith("--deployment=") for a in captured["args"])
