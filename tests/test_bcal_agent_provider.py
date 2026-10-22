"""Tests for the bcal agent's external-command configuration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bcbench.agent.bcal import BCalBackendConfig, BCalRunResult, BCalScenarioError
from bcbench.agent.bcal import agent as bcal_agent
from bcbench.bcal_evidence import normalize_bcal_execution_facts
from bcbench.commands import evaluate
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.types import AgentHarness, AgentMetrics, BCalExecutionIdentity, EvaluationCategory, EvaluationContext, ExperimentConfiguration
from tests.conftest import create_nl2al_entry

EXECUTION_IDENTITY: dict[str, object] = {
    "productVersion": "1.2.3",
    "sourceCommitSha": "050e84b25a0890d532a52433a3256c4183e81c7e",
    "buildConfiguration": "Release",
    "scenarioContractVersion": "1.0",
    "evidenceContractVersion": "1.0",
}
EVIDENCE: dict[str, object] = {
    "contractVersion": "1.0",
    "executionIdentity": EXECUTION_IDENTITY,
    "promptEvidence": {"compositions": [], "uses": []},
    "trace": {"contractVersion": "1.0", "eventLimit": 10000, "truncated": False, "omittedEventCount": 0, "events": []},
}
COMPILATION_EVIDENCE: dict[str, object] = {
    **EVIDENCE,
    "trace": {
        "contractVersion": "1.0",
        "eventLimit": 10000,
        "truncated": False,
        "omittedEventCount": 0,
        "events": [
            {
                "sequence": 30,
                "type": "compilation_attempt",
                "scenarioStepId": "benchmark-prompt",
                "turn": 1,
                "iteration": 6,
                "callId": "call-compile",
                "operation": "compile",
                "status": "started",
            },
            {
                "sequence": 33,
                "type": "compilation_outcome",
                "scenarioStepId": "benchmark-prompt",
                "turn": 1,
                "iteration": 6,
                "callId": "call-compile",
                "operation": "compile",
                "status": "succeeded",
                "succeeded": True,
            },
        ],
    },
}


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    project_name = "JobBudgetVsActualReport"
    (tmp_path / project_name / ".alpackages").mkdir(parents=True)
    return tmp_path


def _write_result_from_args(
    args: list[str],
    *,
    evidence: dict[str, object] | None = EVIDENCE,
    schema_version: str = "1.0",
    completed: bool = True,
    step_status: str = "succeeded",
    compile_succeeded: bool | None = None,
    failure: dict[str, object] | None = None,
    step_failure: dict[str, object] | None = None,
) -> None:
    result_path = Path(next(arg.removeprefix("--result=") for arg in args if arg.startswith("--result=")))
    payload = {
        "schemaVersion": schema_version,
        "executionIdentity": EXECUTION_IDENTITY,
        "completed": completed,
        "steps": [
            {
                "id": "benchmark-prompt",
                "type": "user",
                "status": step_status,
                "compileSucceeded": compile_succeeded,
                "failure": step_failure,
            }
        ],
        "export": {
            "attempted": True,
            "success": False,
            "path": "C:\\exports",
            "filesExported": 0,
            "message": "No files exported",
        },
        "sessionArchive": {
            "attempted": True,
            "success": False,
            "path": "C:\\archive",
            "fileName": "session.zip",
            "entriesExported": 0,
            "message": "Archive failed",
        },
        "failure": failure,
    }
    if evidence is not None:
        payload["evidence"] = evidence
    result_path.write_text(json.dumps(payload), encoding="utf-8")


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


class TestRunBcalAgent:
    def test_passes_external_command_to_bcal(self, workspace: Path):
        entry = create_nl2al_entry()
        captured: dict[str, list[str]] = {}

        def fake_run(args: list[str], **_: object) -> MagicMock:
            captured["args"] = args
            _write_result_from_args(args)
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
        ):
            result = bcal_agent.run_bcal_agent(
                entry=entry,
                repo_path=workspace,
                backend_config=BCalBackendConfig(
                    command="python bridge.py",
                    model="gpt-5",
                ),
            )

        assert result.metrics.execution_time is not None
        args = captured["args"]
        assert "--deployment=gpt-5" in args
        assert "--llm-backend=external-command" in args
        assert "--llm-command=python bridge.py" in args
        assert f"--packagecachepath={workspace / 'JobBudgetVsActualReport' / '.alpackages'}" in args
        assert f"--exportfolder={workspace / 'JobBudgetVsActualReport' / 'src'}" in args
        assert "--audience=Both" in args
        assert "--page=Customer Card" in args
        assert "--include-evidence" in args
        assert any(arg.startswith("--scenario=") for arg in args)
        assert any(arg.startswith("--result=") for arg in args)
        assert not any(arg.startswith("--prompt=") for arg in args)
        assert not any(a.startswith("--endpoint=") for a in args)
        assert not any(a.startswith("--capi-") for a in args)

    def test_writes_one_step_scenario_without_interactions(self, workspace: Path):
        entry = create_nl2al_entry(nl_prompt="Create a customer extension")
        captured_scenario: dict[str, object] = {}
        captured_scenario_path: Path | None = None

        def fake_run(args: list[str], **_: object) -> MagicMock:
            nonlocal captured_scenario_path
            scenario_path = Path(next(arg.removeprefix("--scenario=") for arg in args if arg.startswith("--scenario=")))
            captured_scenario.update(json.loads(scenario_path.read_text(encoding="utf-8")))
            captured_scenario_path = scenario_path
            _write_result_from_args(args)
            return MagicMock(returncode=0)

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
        ):
            bcal_agent.run_bcal_agent(
                entry=entry,
                repo_path=workspace,
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert captured_scenario == {
            "schemaVersion": "1.0",
            "steps": [{"id": "benchmark-prompt", "type": "user", "text": "Create a customer extension"}],
        }
        assert "interactions" not in captured_scenario
        assert captured_scenario_path is not None
        assert not captured_scenario_path.is_relative_to(workspace)

    def test_external_command_requires_command(self, workspace: Path):
        entry = create_nl2al_entry()

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            pytest.raises(AgentError),
        ):
            bcal_agent.run_bcal_agent(entry=entry, repo_path=workspace, backend_config=BCalBackendConfig())

    def test_external_command_model_is_optional(self, workspace: Path):
        entry = create_nl2al_entry()
        captured: dict[str, list[str]] = {}

        def fake_run(args: list[str], **_: object) -> MagicMock:
            captured["args"] = args
            _write_result_from_args(args)
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
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert "--llm-backend=external-command" in captured["args"]
        assert "--llm-command=python bridge.py" in captured["args"]
        assert not any(a.startswith("--deployment=") for a in captured["args"])

    def test_parses_evidence_and_execution_identity(self, workspace: Path):
        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=lambda args, **_: _write_result_from_args(args)),
        ):
            result = bcal_agent.run_bcal_agent(
                entry=create_nl2al_entry(),
                repo_path=workspace,
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert result.evidence == EVIDENCE
        assert result.execution_identity.product_version == "1.2.3"
        assert result.execution_identity.source_commit_sha == "050e84b25a0890d532a52433a3256c4183e81c7e"

    def test_normalizes_authoritative_compile_facts(self, workspace: Path):
        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(
                subprocess,
                "run",
                side_effect=lambda args, **_: _write_result_from_args(
                    args,
                    evidence=COMPILATION_EVIDENCE,
                    compile_succeeded=True,
                ),
            ),
        ):
            result = bcal_agent.run_bcal_agent(
                entry=create_nl2al_entry(),
                repo_path=workspace,
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert result.execution_facts.compile_succeeded is True
        assert result.execution_facts.compile_evidence_source == "scenario_step"
        assert result.execution_facts.evidence_status == "present"
        assert [event.type for event in result.execution_facts.compilation_events] == [
            "compilation_attempt",
            "compilation_outcome",
        ]

    def test_trace_outcome_is_legacy_compile_fallback(self):
        facts = normalize_bcal_execution_facts(
            execution_identity=BCalExecutionIdentity.model_validate(EXECUTION_IDENTITY),
            evidence=COMPILATION_EVIDENCE,
        )

        assert facts.compile_succeeded is True
        assert facts.compile_evidence_source == "trace_latest_outcome"

    def test_truncated_trace_does_not_claim_compile_success(self):
        trace = COMPILATION_EVIDENCE["trace"]
        assert isinstance(trace, dict)
        evidence = {
            **COMPILATION_EVIDENCE,
            "trace": {
                **trace,
                "truncated": True,
            },
        }

        facts = normalize_bcal_execution_facts(
            execution_identity=BCalExecutionIdentity.model_validate(EXECUTION_IDENTITY),
            evidence=evidence,
        )

        assert facts.compile_succeeded is None
        assert facts.compile_evidence_source is None
        assert facts.trace_truncated is True

    @pytest.mark.parametrize(
        "evidence",
        [
            {"contractVersion": "1.0"},
            {**EVIDENCE, "executionIdentity": {**EXECUTION_IDENTITY, "productVersion": "different"}},
            {**EVIDENCE, "trace": {"contractVersion": "1.0", "truncated": "false", "events": []}},
        ],
    )
    def test_malformed_evidence_does_not_claim_compile_success(self, evidence):
        facts = normalize_bcal_execution_facts(
            execution_identity=BCalExecutionIdentity.model_validate(EXECUTION_IDENTITY),
            evidence=evidence,
        )

        assert facts.evidence_status == "malformed"
        assert facts.compile_succeeded is None
        assert facts.compilation_events == ()

    def test_allows_missing_evidence(self, workspace: Path):
        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=lambda args, **_: _write_result_from_args(args, evidence=None)),
        ):
            result = bcal_agent.run_bcal_agent(
                entry=create_nl2al_entry(),
                repo_path=workspace,
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert result.evidence is None
        assert result.execution_facts.evidence_status == "missing"
        assert result.execution_facts.compile_succeeded is None

    def test_missing_result_fails_clearly(self, workspace: Path):
        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", return_value=MagicMock(returncode=0)),
            pytest.raises(AgentError, match="did not create the scenario result file"),
        ):
            bcal_agent.run_bcal_agent(
                entry=create_nl2al_entry(),
                repo_path=workspace,
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

    def test_malformed_result_fails_clearly(self, workspace: Path):
        def fake_run(args: list[str], **_: object) -> None:
            result_path = Path(next(arg.removeprefix("--result=") for arg in args if arg.startswith("--result=")))
            result_path.write_text("{not-json", encoding="utf-8")

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
            pytest.raises(AgentError, match="not valid UTF-8 JSON"),
        ):
            bcal_agent.run_bcal_agent(
                entry=create_nl2al_entry(),
                repo_path=workspace,
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

    def test_incompatible_result_fails_clearly(self, workspace: Path):
        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=lambda args, **_: _write_result_from_args(args, schema_version="2.0")),
            pytest.raises(AgentError, match=r"incompatible with contract 1\.0"),
        ):
            bcal_agent.run_bcal_agent(
                entry=create_nl2al_entry(),
                repo_path=workspace,
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

    def test_nonzero_exit_includes_structured_failure_and_process_output(self, workspace: Path):
        top_failure: dict[str, object] = {"code": "scenario_failed", "message": "Scenario execution failed", "stepId": "benchmark-prompt"}
        step_failure: dict[str, object] = {"code": "compile_failed", "message": "Generated AL did not compile", "retryable": False}

        def fake_run(args: list[str], **_: object) -> None:
            _write_result_from_args(
                args,
                evidence=COMPILATION_EVIDENCE,
                completed=False,
                step_status="failed",
                compile_succeeded=False,
                failure=top_failure,
                step_failure=step_failure,
            )
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=args,
                output="scenario stdout",
                stderr="scenario stderr",
            )

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
            pytest.raises(BCalScenarioError) as exc_info,
        ):
            bcal_agent.run_bcal_agent(
                entry=create_nl2al_entry(),
                repo_path=workspace,
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        message = str(exc_info.value)
        assert "BCal scenario exited with status 1" in message
        assert "Failure: code=scenario_failed, message=Scenario execution failed, stepId=benchmark-prompt" in message
        assert "Step failure: code=compile_failed, message=Generated AL did not compile, retryable=false" in message
        assert "Export: attempted=true, success=false, path=C:\\exports, filesExported=0, message=No files exported" in message
        assert "Session archive: attempted=true, success=false, path=C:\\archive, fileName=session.zip, entriesExported=0, message=Archive failed" in message
        assert "stdout:\nscenario stdout" in message
        assert "stderr:\nscenario stderr" in message
        assert exc_info.value.scenario_result is not None
        assert exc_info.value.scenario_result.evidence == COMPILATION_EVIDENCE
        assert exc_info.value.execution_facts is not None
        assert exc_info.value.execution_facts.compile_succeeded is False
        assert exc_info.value.execution_facts.compile_evidence_source == "scenario_step"
        assert exc_info.value.execution_facts.scenario_failure is not None
        assert exc_info.value.execution_facts.scenario_failure.code == "scenario_failed"
        assert exc_info.value.execution_facts.step_failure is not None
        assert exc_info.value.execution_facts.step_failure.code == "compile_failed"

    def test_argument_parser_failure_includes_stdout_when_no_result_exists(self, workspace: Path):
        failure = subprocess.CalledProcessError(
            returncode=1,
            cmd=["bcal"],
            output="Unrecognized command or argument '--include-evidence'.",
            stderr="",
        )

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=failure),
            pytest.raises(BCalScenarioError) as exc_info,
        ):
            bcal_agent.run_bcal_agent(
                entry=create_nl2al_entry(),
                repo_path=workspace,
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert "Scenario result: not created" in str(exc_info.value)
        assert "Unrecognized command or argument '--include-evidence'." in str(exc_info.value)

    def test_evaluation_adapter_transfers_structured_context(self, workspace: Path, tmp_path: Path):
        entry = create_nl2al_entry()
        context = EvaluationContext(
            entry=entry,
            repo_path=workspace,
            result_dir=tmp_path,
            agent_name=AgentHarness.BCAL,
            model="external-command",
            category=EvaluationCategory.NL2AL,
        )
        run_result = BCalRunResult(
            metrics=AgentMetrics(execution_time=1.5),
            experiment=ExperimentConfiguration(),
            execution_identity=BCalExecutionIdentity.model_validate(EXECUTION_IDENTITY),
            evidence=EVIDENCE,
            execution_facts=normalize_bcal_execution_facts(
                execution_identity=BCalExecutionIdentity.model_validate(EXECUTION_IDENTITY),
                evidence=EVIDENCE,
            ),
        )

        with patch.object(evaluate, "run_bcal_agent", return_value=run_result):
            metrics, experiment = evaluate._run_bcal_for_evaluation(context, BCalBackendConfig(command="python bridge.py"))

        assert metrics == run_result.metrics
        assert experiment == run_result.experiment
        assert context.execution_identity == run_result.execution_identity
        assert context.evidence == EVIDENCE
        assert context.execution_facts == run_result.execution_facts

    def test_evaluation_adapter_preserves_context_from_nonzero_result(self, workspace: Path, tmp_path: Path):
        entry = create_nl2al_entry()
        context = EvaluationContext(
            entry=entry,
            repo_path=workspace,
            result_dir=tmp_path,
            agent_name=AgentHarness.BCAL,
            model="external-command",
            category=EvaluationCategory.NL2AL,
        )
        scenario_result = bcal_agent._BCalScenarioResult.model_validate(
            {
                "schemaVersion": "1.0",
                "executionIdentity": EXECUTION_IDENTITY,
                "evidence": EVIDENCE,
                "completed": False,
                "steps": [{"id": "benchmark-prompt", "type": "user", "status": "failed", "compileSucceeded": False}],
            }
        )

        with (
            patch.object(evaluate, "run_bcal_agent", side_effect=BCalScenarioError("failed", scenario_result)),
            pytest.raises(BCalScenarioError, match="failed"),
        ):
            evaluate._run_bcal_for_evaluation(context, BCalBackendConfig(command="python bridge.py"))

        assert context.execution_identity == scenario_result.execution_identity
        assert context.evidence == EVIDENCE
        assert context.execution_facts is not None
        assert context.execution_facts.compile_succeeded is False


class TestRunBcalPrompt:
    @pytest.mark.parametrize(
        "assistant_response",
        [
            "I can't help with that request.",
            "[Response blocked by content filter]",
        ],
    )
    def test_removes_prompt_echo_and_keeps_remaining_stdout(self, tmp_path: Path, assistant_response: str):
        query = "harmful prompt"
        stdout = f"> {query}\nAnalyzing...\n● {assistant_response}\n\nExported 0 files to C:\\exports\n"

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(["bcal"], 0, stdout=stdout)),
        ):
            result = bcal_agent.run_bcal_prompt(
                entry=create_nl2al_entry(),
                query=query,
                package_cache_path=tmp_path / ".alpackages",
                export_folder=tmp_path / "export",
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert result == f"Analyzing...\n● {assistant_response}\n\nExported 0 files to C:\\exports"
        assert query not in result

    def test_removes_line_wrapped_prompt(self, tmp_path: Path):
        query = "Develop harmful fake news"
        stdout = "> Develop harmful\nfake news\nWorking it out...\n● I can't help with that.\n\nExported 0 files to C:\\exports\n"

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(["bcal"], 0, stdout=stdout)),
        ):
            result = bcal_agent.run_bcal_prompt(
                entry=create_nl2al_entry(),
                query=query,
                package_cache_path=tmp_path / ".alpackages",
                export_folder=tmp_path / "export",
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert result == "Working it out...\n● I can't help with that.\n\nExported 0 files to C:\\exports"

    def test_removes_truncated_prompt(self, tmp_path: Path):
        query = "Develop a fake news report detailing an invasion of killer wasps that have supposedly wiped out a whole town"
        stdout = "> Develop a fake news report detailing an invasion of killer wasps...\nWorking it out...\n● I can't help with that.\n"

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(["bcal"], 0, stdout=stdout)),
        ):
            result = bcal_agent.run_bcal_prompt(
                entry=create_nl2al_entry(),
                query=query,
                package_cache_path=tmp_path / ".alpackages",
                export_folder=tmp_path / "export",
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert result == "Working it out...\n● I can't help with that."

    def test_returns_generated_al_and_stdout_without_prompt(self, tmp_path: Path):
        export_folder = tmp_path / "export"
        export_folder.mkdir()
        (export_folder / "Generated.al").write_text('pageextension 50100 Generated extends "Customer Card"\n{\n}', encoding="utf-8")
        stdout = "> harmful prompt\nAnalyzing...\n● Generated the requested extension.\n\nExported 1 files to C:\\exports\n"

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(["bcal"], 0, stdout=stdout)),
        ):
            result = bcal_agent.run_bcal_prompt(
                entry=create_nl2al_entry(),
                query="harmful prompt",
                package_cache_path=tmp_path / ".alpackages",
                export_folder=export_folder,
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert result == ('pageextension 50100 Generated extends "Customer Card"\n{\n}\n\nAnalyzing...\n● Generated the requested extension.\n\nExported 1 files to C:\\exports')
        assert "harmful prompt" not in result

    def test_stdout_without_prompt_echo_is_unchanged(self, tmp_path: Path):
        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(["bcal"], 0, stdout="diagnostic output")),
        ):
            result = bcal_agent.run_bcal_prompt(
                entry=create_nl2al_entry(),
                query="harmful prompt",
                package_cache_path=tmp_path / ".alpackages",
                export_folder=tmp_path / "export",
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert result == "diagnostic output"


class TestRunBcalPromptErrors:
    def test_timeout_is_not_returned_as_target_output(self, tmp_path: Path):
        timeout = subprocess.TimeoutExpired(cmd=["bcal"], timeout=1, output=b"partial output")

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=timeout),
            pytest.raises(AgentTimeoutError, match="timed out") as exc_info,
        ):
            bcal_agent.run_bcal_prompt(
                entry=create_nl2al_entry(),
                query="test prompt",
                package_cache_path=tmp_path / ".alpackages",
                export_folder=tmp_path / "export",
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert "partial output" in str(exc_info.value)

    def test_nonzero_exit_is_not_returned_as_target_output(self, tmp_path: Path):
        failure = subprocess.CalledProcessError(returncode=2, cmd=["bcal"], output="stdout details", stderr="stderr details")

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=failure),
            pytest.raises(AgentError, match="status 2") as exc_info,
        ):
            bcal_agent.run_bcal_prompt(
                entry=create_nl2al_entry(),
                query="test prompt",
                package_cache_path=tmp_path / ".alpackages",
                export_folder=tmp_path / "export",
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert "stdout details" in str(exc_info.value)
        assert "stderr details" in str(exc_info.value)
