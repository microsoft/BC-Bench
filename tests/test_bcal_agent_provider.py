"""Tests for the bcal agent's LLM backend branch."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bcbench.agent.bcal import agent as bcal_agent
from bcbench.agent.bcal.agent import BcalLlmBackend
from bcbench.exceptions import AgentError
from tests.conftest import create_nl2al_entry

_RELEVANT_ENV_VARS = (
    "BCAL_LLM_BACKEND",
    "BCAL_LLM_MODEL",
    "BCAL_LLM_COMMAND",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT",
)


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _RELEVANT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    project_name = "JobBudgetVsActualReport"
    (tmp_path / project_name / ".alpackages").mkdir(parents=True)
    return tmp_path


class TestResolveLlmBackend:
    def test_default_is_azure_openai(self):
        assert bcal_agent._resolve_llm_backend() is BcalLlmBackend.AZURE_OPENAI

    def test_explicit_azure_openai(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BCAL_LLM_BACKEND", "azure-openai")
        assert bcal_agent._resolve_llm_backend() is BcalLlmBackend.AZURE_OPENAI

    def test_external_command(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BCAL_LLM_BACKEND", "external-command")
        assert bcal_agent._resolve_llm_backend() is BcalLlmBackend.EXTERNAL_COMMAND

    def test_unknown_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BCAL_LLM_BACKEND", "openai")
        with pytest.raises(AgentError):
            bcal_agent._resolve_llm_backend()


class TestRunBcalAgentAzureOpenAI:
    def test_passes_aoai_endpoint_to_subprocess(self, workspace: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://aoai.example/")
        monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.2")
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
            metrics, _ = bcal_agent.run_bcal_agent(entry=entry, repo_path=workspace)

        assert metrics is not None
        assert "--endpoint=https://aoai.example/" in captured["args"]
        assert "--deployment=gpt-5.2" in captured["args"]
        assert not any(a.startswith("--llm-backend=") for a in captured["args"])


class TestRunBcalAgentExternalCommand:
    def _external_command_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BCAL_LLM_BACKEND", "external-command")
        monkeypatch.setenv("BCAL_LLM_MODEL", "gpt-5")
        monkeypatch.setenv("BCAL_LLM_COMMAND", "python bridge.py")

    def test_passes_external_command_backend_to_bcal(self, workspace: Path, monkeypatch: pytest.MonkeyPatch):
        self._external_command_env(monkeypatch)
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
            metrics, _ = bcal_agent.run_bcal_agent(entry=entry, repo_path=workspace)

        assert metrics is not None
        args = captured["args"]
        assert "--deployment=gpt-5" in args
        assert "--llm-backend=external-command" in args
        assert "--llm-command=python bridge.py" in args
        assert not any(a.startswith("--endpoint=") for a in args)
        assert not any(a.startswith("--capi-") for a in args)

    def test_external_command_requires_command(self, workspace: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BCAL_LLM_BACKEND", "external-command")
        entry = create_nl2al_entry()

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            pytest.raises(AgentError),
        ):
            bcal_agent.run_bcal_agent(entry=entry, repo_path=workspace)

    def test_external_command_model_is_optional(self, workspace: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BCAL_LLM_BACKEND", "external-command")
        monkeypatch.setenv("BCAL_LLM_COMMAND", "python bridge.py")
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
            bcal_agent.run_bcal_agent(entry=entry, repo_path=workspace)

        assert "--llm-backend=external-command" in captured["args"]
        assert "--llm-command=python bridge.py" in captured["args"]
        assert not any(a.startswith("--deployment=") for a in captured["args"])
