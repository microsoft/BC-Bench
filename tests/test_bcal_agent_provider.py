"""Tests for the bcal agent's provider branch (azure-openai vs capi)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bcbench.agent.bcal import agent as bcal_agent
from bcbench.agent.bcal.agent import BcalAIProvider
from bcbench.exceptions import AgentError
from tests.conftest import create_nl2al_entry

_RELEVANT_ENV_VARS = (
    "BCAL_AI_PROVIDER",
    "BCAL_AI_MODEL",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT",
    "CAPI_ENDPOINT",
    "CAPI_SCOPE",
    "CAPI_ORG_GUID",
    "CAPI_TENANT_ID",
    "CAPI_USER_OBJECT_ID",
    "CAPI_PARTNER_SOURCE",
    "CAPI_CLIENT_ID",
    "CAPI_CERTIFICATE_KEY_VAULT_NAME",
    "CAPI_CERTIFICATE_NAME",
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


class TestResolveProvider:
    def test_default_is_azure_openai(self):
        assert bcal_agent._resolve_provider() is BcalAIProvider.AZURE_OPENAI

    def test_explicit_azure_openai(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BCAL_AI_PROVIDER", "azure-openai")
        assert bcal_agent._resolve_provider() is BcalAIProvider.AZURE_OPENAI

    def test_capi(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BCAL_AI_PROVIDER", "capi")
        assert bcal_agent._resolve_provider() is BcalAIProvider.CAPI

    def test_unknown_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BCAL_AI_PROVIDER", "openai")
        with pytest.raises(AgentError):
            bcal_agent._resolve_provider()


class TestResolveDeployment:
    def test_azure_openai_requires_aoai_deployment(self):
        with pytest.raises(AgentError):
            bcal_agent._resolve_deployment(BcalAIProvider.AZURE_OPENAI)

    def test_capi_prefers_bcal_ai_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BCAL_AI_MODEL", "gpt-5")
        monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.2")
        assert bcal_agent._resolve_deployment(BcalAIProvider.CAPI) == "gpt-5"

    def test_capi_falls_back_to_aoai_deployment(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.2")
        assert bcal_agent._resolve_deployment(BcalAIProvider.CAPI) == "gpt-5.2"


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
        assert not any(a.startswith("--ai-provider=") for a in captured["args"])


class TestRunBcalAgentCapi:
    def _capi_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BCAL_AI_PROVIDER", "capi")
        monkeypatch.setenv("BCAL_AI_MODEL", "gpt-5")
        monkeypatch.setenv("CAPI_ENDPOINT", "https://capi.example")
        monkeypatch.setenv("CAPI_SCOPE", "api://capi/.default")
        monkeypatch.setenv("CAPI_ORG_GUID", "org-guid-1")
        monkeypatch.setenv("CAPI_TENANT_ID", "tenant-1")
        monkeypatch.setenv("CAPI_USER_OBJECT_ID", "user-1")

    def test_forwards_provider_neutral_capi_args_to_bcal_cli(self, workspace: Path, monkeypatch: pytest.MonkeyPatch):
        self._capi_env(monkeypatch)
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
        assert "--endpoint=https://capi.example" in args
        assert "--deployment=gpt-5" in args
        assert "--ai-provider=capi" in args
        assert not any(a.startswith("--capi-") for a in args)

    def test_partner_source_stays_env_only(self, workspace: Path, monkeypatch: pytest.MonkeyPatch):
        self._capi_env(monkeypatch)
        monkeypatch.setenv("CAPI_PARTNER_SOURCE", "BC.NL2AL.Test")
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

        assert not any(a.startswith("--capi-partner-source=") for a in captured["args"])

    @pytest.mark.parametrize(
        "missing",
        ["CAPI_ENDPOINT", "CAPI_SCOPE", "CAPI_ORG_GUID", "CAPI_TENANT_ID", "CAPI_USER_OBJECT_ID"],
    )
    def test_missing_required_capi_var_raises(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch, missing: str
    ):
        self._capi_env(monkeypatch)
        monkeypatch.delenv(missing, raising=False)
        entry = create_nl2al_entry()

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run") as run_mock,
            pytest.raises(AgentError) as exc,
        ):
            bcal_agent.run_bcal_agent(entry=entry, repo_path=workspace)

        assert missing in str(exc.value)
        run_mock.assert_not_called()

    def test_cert_env_accepted_when_all_three_set(self, workspace: Path, monkeypatch: pytest.MonkeyPatch):
        self._capi_env(monkeypatch)
        monkeypatch.setenv("CAPI_CLIENT_ID", "client-1")
        monkeypatch.setenv("CAPI_CERTIFICATE_KEY_VAULT_NAME", "kv-1")
        monkeypatch.setenv("CAPI_CERTIFICATE_NAME", "cert-1")
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

        args = captured["args"]
        assert not any(a.startswith("--capi-") for a in args)

    def test_cert_env_omitted_when_none_set(self, workspace: Path, monkeypatch: pytest.MonkeyPatch):
        self._capi_env(monkeypatch)
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

        assert not any(a.startswith("--capi-") for a in captured["args"])

    @pytest.mark.parametrize(
        "missing",
        ["CAPI_CLIENT_ID", "CAPI_CERTIFICATE_KEY_VAULT_NAME", "CAPI_CERTIFICATE_NAME"],
    )
    def test_partial_cert_config_raises(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch, missing: str
    ):
        self._capi_env(monkeypatch)
        monkeypatch.setenv("CAPI_CLIENT_ID", "client-1")
        monkeypatch.setenv("CAPI_CERTIFICATE_KEY_VAULT_NAME", "kv-1")
        monkeypatch.setenv("CAPI_CERTIFICATE_NAME", "cert-1")
        monkeypatch.delenv(missing, raising=False)
        entry = create_nl2al_entry()

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run") as run_mock,
            pytest.raises(AgentError) as exc,
        ):
            bcal_agent.run_bcal_agent(entry=entry, repo_path=workspace)

        assert "cert auth requires all" in str(exc.value)
        run_mock.assert_not_called()
