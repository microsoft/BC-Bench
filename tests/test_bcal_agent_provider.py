"""Tests for the bcal agent's external-command configuration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from bcbench_core.agent.harness import AgentRequest, AgentResult
from bcbench_core.exceptions import AgentError, AgentTimeoutError

from bcbench.agent.bcal import BCalBackendConfig
from bcbench.agent.bcal import agent as bcal_agent
from bcbench.dataset import NL2ALEntry
from tests.conftest import create_nl2al_entry


def _arg_path(args: list[str], flag: str) -> Path:
    return Path(next(arg.removeprefix(f"{flag}=") for arg in args if arg.startswith(f"{flag}=")))


RESULT: dict[str, object] = {
    "schemaVersion": "1.0",
    "executionIdentity": {"productVersion": "1.2.3"},
    "completed": True,
    "steps": [{"id": "benchmark-prompt", "type": "user", "status": "succeeded", "compileSucceeded": True}],
    "evidence": {"contractVersion": "1.0", "trace": {"events": [{"type": "tool", "name": "compile"}]}},
}


def _write_result(args: list[str], result: dict[str, object] = RESULT) -> None:
    _arg_path(args, "--result").write_text(json.dumps(result), encoding="utf-8")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    project_name = "JobBudgetVsActualReport"
    (tmp_path / project_name / ".alpackages").mkdir(parents=True)
    return tmp_path


class TestCliArgs:
    def test_string_inputs_are_stripped(self):
        config = BCalBackendConfig(command=" python bridge.py ", model=" gpt-5 ")
        assert config.cli_args() == ["--llm-backend=external-command", "--llm-command=python bridge.py", "--deployment=gpt-5"]

    def test_includes_command_and_model(self):
        args = BCalBackendConfig(command="python bridge.py", model="gpt-5").cli_args()
        assert "--llm-backend=external-command" in args
        assert "--llm-command=python bridge.py" in args
        assert "--deployment=gpt-5" in args
        assert not any(a.startswith("--endpoint=") for a in args)

    def test_requires_command(self):
        with pytest.raises(AgentError, match="BCAL_LLM_COMMAND is required"):
            BCalBackendConfig(model="gpt-5").cli_args()

    def test_whitespace_only_required_values_are_missing(self):
        with pytest.raises(AgentError):
            BCalBackendConfig(command="   ").cli_args()

    def test_model_is_optional(self):
        args = BCalBackendConfig(command="python bridge.py").cli_args()
        assert "--llm-backend=external-command" in args
        assert "--llm-command=python bridge.py" in args
        assert not any(a.startswith("--deployment=") for a in args)


def _run_bcal(entry: NL2ALEntry, workspace: Path, backend_config: BCalBackendConfig) -> AgentResult:
    return bcal_agent.BCalHarness(backend_config).run(AgentRequest(task=entry, work_dir=workspace, output_dir=workspace))


class TestRunBcalAgent:
    def test_passes_external_command_to_bcal(self, workspace: Path):
        entry = create_nl2al_entry()
        captured: dict[str, list[str]] = {}

        def fake_run(args: list[str], **_: object) -> MagicMock:
            captured["args"] = args
            _write_result(args)
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
        ):
            result = _run_bcal(entry, workspace, BCalBackendConfig(command="python bridge.py", model="gpt-5"))

        assert result.metrics is not None
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
            _run_bcal(entry, workspace, BCalBackendConfig())

    def test_external_command_model_is_optional(self, workspace: Path):
        entry = create_nl2al_entry()
        captured: dict[str, list[str]] = {}

        def fake_run(args: list[str], **_: object) -> MagicMock:
            captured["args"] = args
            _write_result(args)
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
        ):
            _run_bcal(entry, workspace, BCalBackendConfig(command="python bridge.py"))

        assert "--llm-backend=external-command" in captured["args"]
        assert "--llm-command=python bridge.py" in captured["args"]
        assert not any(a.startswith("--deployment=") for a in captured["args"])

    def test_runs_one_step_scenario_and_returns_result_as_transcript(self, workspace: Path):
        entry = create_nl2al_entry(nl_prompt="Create a customer extension")
        captured: dict[str, list[str]] = {}
        scenarios: list[object] = []

        def fake_run(args: list[str], **_: object) -> MagicMock:
            captured["args"] = args
            scenarios.append(json.loads(_arg_path(args, "--scenario").read_text(encoding="utf-8")))
            _write_result(args)
            return MagicMock(returncode=0)

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
        ):
            result = _run_bcal(entry, workspace, BCalBackendConfig(command="python bridge.py"))

        assert scenarios == [{"schemaVersion": "1.0", "steps": [{"id": "benchmark-prompt", "type": "user", "text": "Create a customer extension"}]}]
        assert "--include-evidence" in captured["args"]
        assert not any(arg.startswith("--prompt=") for arg in captured["args"])
        assert result.transcript == RESULT

    def test_unsupported_result_schema_fails(self, workspace: Path):
        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=lambda args, **_: _write_result(args, {**RESULT, "schemaVersion": "2.0"})),
            pytest.raises(AgentError, match="Unsupported BCal scenario result"),
        ):
            _run_bcal(create_nl2al_entry(), workspace, BCalBackendConfig(command="python bridge.py"))

    def test_accepts_result_schema_1_1_from_older_builds(self, workspace: Path):
        result_1_1 = {**RESULT, "schemaVersion": "1.1"}
        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=lambda args, **_: _write_result(args, result_1_1)),
        ):
            result = _run_bcal(create_nl2al_entry(), workspace, BCalBackendConfig(command="python bridge.py"))

        assert result.transcript == result_1_1

    def test_missing_result_after_success_fails(self, workspace: Path):
        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", return_value=MagicMock(returncode=0)),
            pytest.raises(AgentError, match="Could not read BCal scenario result"),
        ):
            _run_bcal(create_nl2al_entry(), workspace, BCalBackendConfig(command="python bridge.py"))

    @pytest.mark.parametrize("writes_result", [True, False])
    @pytest.mark.parametrize(
        ("failure", "expected_error"),
        [
            (subprocess.CalledProcessError(returncode=1, cmd=["bcal"]), AgentError),
            (subprocess.TimeoutExpired(cmd=["bcal"], timeout=1), AgentTimeoutError),
        ],
    )
    def test_failure_keeps_transcript_when_available(self, workspace: Path, writes_result: bool, failure: Exception, expected_error: type[AgentError]):
        def fake_run(args: list[str], **_: object) -> None:
            if writes_result:
                _write_result(args)
            raise failure

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
            pytest.raises(expected_error) as exc_info,
        ):
            _run_bcal(create_nl2al_entry(), workspace, BCalBackendConfig(command="python bridge.py"))

        assert exc_info.value.transcript == (RESULT if writes_result else None)


@pytest.mark.parametrize("exit_code", [0, 2])
def test_prompt_runner_preserves_private_process_evidence_not_scoring_text(tmp_path, monkeypatch, capsys, exit_code):
    def popen(args, *, cwd, stdout, stderr):
        assert "--page=Customer Card" in args
        assert "--audience=Business" in args
        assert "--prompt=Test prompt" in args
        assert "--log-full" in args
        assert "--include-evidence" not in args  # BCal prohibits scenario mode with harms fixtures.
        stdout.write(b"Test prompt\nprivate diagnostic")
        stderr.write(b"private failure")
        return type("Process", (), {"wait": lambda self, timeout: exit_code})()

    monkeypatch.setattr(subprocess, "Popen", popen)
    result = bcal_agent.run_bcal_prompt(
        query="Test prompt",
        page="Customer Card",
        audience="Business",
        package_cache_path=tmp_path / "symbols",
        export_folder=tmp_path / "export",
        backend_config=BCalBackendConfig(command="python bridge.py"),
        executable=tmp_path / "bcal.exe",
        output=tmp_path,
    )
    assert result.exit_code == exit_code
    assert not result.timed_out
    assert (tmp_path / "stdout.txt").read_bytes() == b"Test prompt\nprivate diagnostic"
    assert (tmp_path / "stderr.txt").read_bytes() == b"private failure"
    assert json.loads((tmp_path / "process.json").read_text())["exit_code"] == exit_code
    assert capsys.readouterr().out == ""
