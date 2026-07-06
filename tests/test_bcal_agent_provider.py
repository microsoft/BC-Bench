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


class TestRunBcalPromptResponse:
    """The captured response is one channel: full generated AL if any, else the chat/stdout."""

    def _run(self, package_cache: Path, export_folder: Path, stdout: str, *, returncode: int = 0) -> str:
        entry = create_nl2al_entry()

        def fake_run(args: list[str], **_: object) -> MagicMock:
            mock = MagicMock()
            mock.returncode = returncode
            mock.stdout = stdout
            mock.stderr = ""
            if returncode != 0:
                raise subprocess.CalledProcessError(returncode, args, output=stdout, stderr="")
            return mock

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
        ):
            return bcal_agent.run_bcal_prompt(
                entry,
                "do something",
                package_cache,
                export_folder,
                BCalBackendConfig(backend=BCalLLMBackend.AZURE_OPENAI, endpoint="https://aoai.example/", deployment="gpt-5.2"),
            )

    def test_full_al_only_when_al_generated(self, tmp_path: Path):
        export = tmp_path / "exp"
        export.mkdir()
        (export / "a.PageExt.al").write_text("pageextension 50100 Ext extends \"Customer Card\" { }", encoding="utf-8")
        (export / "sub" / "b.TableExt.al").parent.mkdir()
        (export / "sub" / "b.TableExt.al").write_text("tableextension 50100 TExt extends Customer { }", encoding="utf-8")

        response = self._run(tmp_path, export, "CHAT SUMMARY that must not leak into the response")

        assert "CHAT SUMMARY" not in response
        assert "pageextension 50100" in response
        assert "tableextension 50100" in response  # full AL across all files, recursively

    def test_stdout_when_no_al_generated(self, tmp_path: Path):
        export = tmp_path / "exp"
        export.mkdir()

        response = self._run(tmp_path, export, "I can't do that — it would exfiltrate data.")

        assert response == "I can't do that — it would exfiltrate data."

    def test_no_output_placeholder_when_nothing(self, tmp_path: Path):
        export = tmp_path / "exp"
        export.mkdir()

        assert self._run(tmp_path, export, "   ") == "(bcal produced no output)"

    def test_generated_al_preferred_even_on_nonzero_exit(self, tmp_path: Path):
        export = tmp_path / "exp"
        export.mkdir()
        (export / "gen.al").write_text("codeunit 50100 Foo { }", encoding="utf-8")

        response = self._run(tmp_path, export, "some error text", returncode=1)

        assert response == "codeunit 50100 Foo { }"

