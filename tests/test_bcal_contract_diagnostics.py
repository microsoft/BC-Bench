from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from bcbench.agent.bcal import BCalBackendConfig, BCalResultDiagnostics, BCalScenarioError, BCalTimeoutError, resolve_bcal_timeout_seconds
from bcbench.agent.bcal import agent as bcal_agent
from bcbench.cli import app
from bcbench.commands import evaluate
from bcbench.config import get_config
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.bceval_export import _judge_context, _outcome_metadata
from bcbench.types import AgentHarness, AgentMetrics, BCalScenarioFailure, EvaluationCategory, EvaluationContext
from tests.conftest import create_nl2al_entry

IDENTITY_1_1: dict[str, object] = {
    "productVersion": "30.0.45.28111",
    "sourceCommitSha": "6954e4238aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "buildConfiguration": "Release",
    "scenarioContractVersion": "1.0",
    "evidenceContractVersion": "1.1",
}
EVIDENCE_1_1: dict[str, object] = {
    "contractVersion": "1.1",
    "executionIdentity": IDENTITY_1_1,
    "promptEvidence": {"compositions": [], "uses": []},
    "trace": {
        "contractVersion": "1.1",
        "eventLimit": 10000,
        "truncated": False,
        "omittedEventCount": 0,
        "events": [{"type": "turn_interrupted", "reason": "absolute_safety_limit"}],
    },
}
OUTCOME: dict[str, object] = {
    "contractVersion": "1.0",
    "workStatus": "absolute_safety_limit",
    "scenarioCompleted": False,
    "configuredStepCount": 1,
    "executedStepCount": 1,
    "successfulStepCount": 0,
    "failedStepCount": 1,
    "terminalStep": {
        "id": "benchmark-prompt",
        "type": "user",
        "status": "failed",
        "planLifecycle": "InProgress",
        "validationState": "Succeeded",
        "deploymentState": "NotAttempted",
        "interruptionReason": "AbsoluteSafetyLimit",
    },
    "projectExport": {"attempted": True, "succeeded": True},
    "sessionArchive": {"attempted": True, "succeeded": True},
}


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "JobBudgetVsActualReport" / ".alpackages").mkdir(parents=True)
    return tmp_path


def _context(workspace: Path, tmp_path: Path, **kwargs: object) -> EvaluationContext:
    return EvaluationContext(
        entry=kwargs.pop("entry", create_nl2al_entry()),
        repo_path=workspace,
        result_dir=tmp_path,
        agent_name=AgentHarness.BCAL,
        model="external-command",
        category=EvaluationCategory.NL2AL,
        **kwargs,
    )


def _payload(*, identity: dict[str, object] = IDENTITY_1_1, outcome: dict[str, object] | None = OUTCOME, evidence: dict[str, object] | None = EVIDENCE_1_1) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "1.0",
        "executionIdentity": identity,
        "completed": True,
        "steps": [{"id": "benchmark-prompt", "type": "user", "status": "succeeded"}],
    }
    if evidence is not None:
        payload["evidence"] = evidence
    if outcome is not None:
        payload["outcome"] = outcome
    return payload


def _result_path(args: list[str]) -> Path:
    return Path(next(arg.removeprefix("--result=") for arg in args if arg.startswith("--result=")))


def _run(workspace: Path, payload: dict[str, object] | str, **kwargs: object):
    def fake_run(args: list[str], **_: object) -> None:
        _result_path(args).write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")

    with (
        patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
        patch.object(subprocess, "run", side_effect=fake_run),
    ):
        return bcal_agent.run_bcal_agent(entry=create_nl2al_entry(), repo_path=workspace, backend_config=BCalBackendConfig(command="python bridge.py"), **kwargs)


class TestEvidenceContractVersions:
    def test_accepts_evidence_1_1_and_persists_outcome(self, workspace: Path):
        result = _run(workspace, _payload())

        assert result.execution_identity.evidence_contract_version == "1.1"
        assert result.evidence == EVIDENCE_1_1
        assert result.outcome == OUTCOME

    def test_tolerates_missing_outcome_for_evidence_1_0(self, workspace: Path):
        identity_1_0 = {**IDENTITY_1_1, "evidenceContractVersion": "1.0"}

        result = _run(workspace, _payload(identity=identity_1_0, outcome=None, evidence=None))

        assert result.execution_identity.evidence_contract_version == "1.0"
        assert result.outcome is None

    def test_adapter_transfers_outcome_to_context_and_result(self, workspace: Path, tmp_path: Path):
        context = _context(workspace, tmp_path)
        run_result = bcal_agent.BCalRunResult(
            metrics=AgentMetrics(execution_time=1.0),
            experiment=MagicMock(),
            execution_identity=bcal_agent.BCalExecutionIdentity.model_validate(IDENTITY_1_1),
            evidence=EVIDENCE_1_1,
            outcome=OUTCOME,
        )

        with patch.object(evaluate, "run_bcal_agent", return_value=run_result):
            evaluate._run_bcal_for_evaluation(context, BCalBackendConfig(command="python bridge.py"))

        assert context.outcome == OUTCOME
        assert JudgeBasedEvaluationResult.create_raw(context, output="diff").outcome == OUTCOME


class TestContractViolationDiagnostics:
    def test_unsupported_evidence_version_preserves_salvaged_fields(self, workspace: Path):
        identity_unknown = {**IDENTITY_1_1, "evidenceContractVersion": "9.9"}
        failure = {"code": "incomplete_execution", "message": "absolute_safety_limit", "stepId": "benchmark-prompt"}
        payload = {**_payload(identity=identity_unknown), "failure": failure}

        with pytest.raises(BCalScenarioError, match="incompatible with the supported contracts") as exc_info:
            _run(workspace, payload)

        diagnostics = exc_info.value.diagnostics
        assert diagnostics.outcome == OUTCOME
        assert diagnostics.evidence == EVIDENCE_1_1
        assert diagnostics.failure == BCalScenarioFailure.model_validate(failure)
        assert diagnostics.execution_identity is None
        assert diagnostics.raw_result is not None
        assert json.loads(diagnostics.raw_result) == payload
        assert exc_info.value.metrics is not None

    def test_invalid_json_preserves_raw_text(self, workspace: Path):
        with pytest.raises(BCalScenarioError, match="not valid UTF-8 JSON") as exc_info:
            _run(workspace, "{truncated")

        assert exc_info.value.diagnostics.raw_result == "{truncated"
        assert exc_info.value.diagnostics.outcome is None

    def test_salvaged_raw_result_is_bounded(self):
        raw_text = json.dumps({"schemaVersion": "1.0", "padding": "x" * (bcal_agent._RAW_RESULT_LIMIT * 2)})

        diagnostics = BCalResultDiagnostics.salvage(raw_text)

        assert diagnostics.raw_result is not None
        assert len(diagnostics.raw_result) < bcal_agent._RAW_RESULT_LIMIT + 100
        assert diagnostics.raw_result.endswith(f"[truncated {len(raw_text) - bcal_agent._RAW_RESULT_LIMIT} characters]")

    def test_salvage_reads_benchmark_step_failure_when_top_level_missing(self):
        step_failure = {"code": "compile_failed", "message": "did not compile"}
        raw_text = json.dumps({"steps": [{"id": "other"}, {"id": "benchmark-prompt", "failure": step_failure}]})

        assert BCalResultDiagnostics.salvage(raw_text).failure == BCalScenarioFailure.model_validate(step_failure)

    def test_adapter_and_failure_row_keep_diagnostics_and_generated_patch(self, workspace: Path, tmp_path: Path):
        context = _context(workspace, tmp_path)
        diagnostics = BCalResultDiagnostics(evidence=EVIDENCE_1_1, outcome=OUTCOME, raw_result='{"schemaVersion":"9.9"}')
        error = BCalScenarioError("incompatible", diagnostics=diagnostics, metrics=AgentMetrics(execution_time=42.0))

        with patch.object(evaluate, "run_bcal_agent", side_effect=error), pytest.raises(BCalScenarioError):
            evaluate._run_bcal_for_evaluation(context, BCalBackendConfig(command="python bridge.py"))
        with patch.object(evaluate, "stage_and_get_diff", return_value="diff --git a/x.al b/x.al") as get_diff:
            output = evaluate._get_preserved_bcal_output(context)
        result = JudgeBasedEvaluationResult.create_failure(context, output=output, error_message=str(error))

        get_diff.assert_called_once()
        assert result.output == "diff --git a/x.al b/x.al"
        assert result.outcome == OUTCOME
        assert result.evidence == EVIDENCE_1_1
        assert result.bcal_raw_result == '{"schemaVersion":"9.9"}'
        assert result.metrics == AgentMetrics(execution_time=42.0)


class TestBCalTimeout:
    def test_resolution_prefers_override_then_entry_then_default(self):
        default_seconds = get_config().timeout.bcal_execution
        entry_with_budget = create_nl2al_entry().model_copy(update={"bcal_timeout_minutes": 75})

        assert resolve_bcal_timeout_seconds(create_nl2al_entry()) == default_seconds
        assert resolve_bcal_timeout_seconds(entry_with_budget) == 75 * 60
        assert resolve_bcal_timeout_seconds(entry_with_budget, override_minutes=10) == 10 * 60

    def test_passes_resolved_timeout_to_process(self, workspace: Path):
        captured: dict[str, object] = {}

        def fake_run(args: list[str], **kwargs: object) -> None:
            captured.update(kwargs)
            _result_path(args).write_text(json.dumps(_payload()), encoding="utf-8")

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
        ):
            bcal_agent.run_bcal_agent(
                entry=create_nl2al_entry().model_copy(update={"bcal_timeout_minutes": 75}),
                repo_path=workspace,
                backend_config=BCalBackendConfig(command="python bridge.py"),
            )

        assert captured["timeout"] == 75 * 60

    def test_timeout_salvages_partial_result_file(self, workspace: Path):
        def fake_run(args: list[str], **_: object) -> None:
            _result_path(args).write_text(json.dumps({"outcome": OUTCOME, "evidence": EVIDENCE_1_1}), encoding="utf-8")
            raise subprocess.TimeoutExpired(cmd=args, timeout=60, output="last stdout", stderr="")

        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=fake_run),
            pytest.raises(BCalTimeoutError) as exc_info,
        ):
            bcal_agent.run_bcal_agent(entry=create_nl2al_entry(), repo_path=workspace, backend_config=BCalBackendConfig(command="python bridge.py"), timeout_seconds=60)

        assert exc_info.value.metrics == AgentMetrics(execution_time=60)
        assert exc_info.value.diagnostics.outcome == OUTCOME
        assert exc_info.value.diagnostics.evidence == EVIDENCE_1_1

    def test_timeout_without_result_file_has_empty_diagnostics(self, workspace: Path):
        with (
            patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
            patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="bcal", timeout=60)),
            pytest.raises(BCalTimeoutError) as exc_info,
        ):
            bcal_agent.run_bcal_agent(entry=create_nl2al_entry(), repo_path=workspace, backend_config=BCalBackendConfig(command="python bridge.py"), timeout_seconds=60)

        assert exc_info.value.diagnostics == BCalResultDiagnostics()

    def test_timeout_row_keeps_partial_output_and_diagnostics(self, workspace: Path, tmp_path: Path):
        context = _context(workspace, tmp_path)
        error = BCalTimeoutError("timed out", diagnostics=BCalResultDiagnostics(evidence=EVIDENCE_1_1, outcome=OUTCOME), metrics=AgentMetrics(execution_time=4500))

        with (
            patch.object(evaluate, "run_bcal_agent", side_effect=error),
            patch.object(evaluate, "stage_and_get_diff", return_value="diff --git a/p.al b/p.al"),
            pytest.raises(BCalTimeoutError),
        ):
            evaluate._run_bcal_for_evaluation(context, BCalBackendConfig(command="python bridge.py"), timeout_minutes=75)
        result = JudgeBasedEvaluationResult.create_agent_timeout_failure(context)

        assert result.timeout is True
        assert result.output == "diff --git a/p.al b/p.al"
        assert result.outcome == OUTCOME
        assert result.evidence == EVIDENCE_1_1

    def test_adapter_passes_run_override_to_agent(self, workspace: Path, tmp_path: Path):
        context = _context(workspace, tmp_path)

        with patch.object(evaluate, "run_bcal_agent", side_effect=BCalScenarioError("stop")) as run_agent, pytest.raises(BCalScenarioError):
            evaluate._run_bcal_for_evaluation(context, BCalBackendConfig(command="python bridge.py"), timeout_minutes=12)

        assert run_agent.call_args.kwargs["timeout_seconds"] == 12 * 60


class TestBCalTimeoutCommand:
    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            ([], ("75", "80")),
            (["--override-minutes", "30"], ("30", "35")),
        ],
    )
    def test_writes_step_outputs_for_control_tower(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str], expected: tuple[str, str]):
        github_output = tmp_path / "github_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

        result = CliRunner().invoke(
            app,
            ["dataset", "bcal-timeout", "nl2al__collected-sales-operations-control-tower-1", "--dataset", "challenge", "--github-output", *args],
        )

        assert result.exit_code == 0, result.output
        assert result.output.strip() == expected[0]
        outputs = github_output.read_text(encoding="utf-8")
        assert f"bcal-timeout-minutes={expected[0]}" in outputs
        assert f"step-timeout-minutes={expected[1]}" in outputs


class TestJudgeContextExport:
    def _result(self, workspace: Path, tmp_path: Path, **kwargs: object) -> JudgeBasedEvaluationResult:
        return JudgeBasedEvaluationResult.create_raw(_context(workspace, tmp_path, **kwargs), output="")

    def test_context_includes_outcome_beside_evidence(self, workspace: Path, tmp_path: Path):
        result = self._result(workspace, tmp_path, evidence=EVIDENCE_1_1, outcome=OUTCOME)

        assert _judge_context(result) == {"outcome": OUTCOME, "evidence": EVIDENCE_1_1}

    def test_context_without_outcome_is_legacy_evidence(self, workspace: Path, tmp_path: Path):
        assert _judge_context(self._result(workspace, tmp_path, evidence=EVIDENCE_1_1)) == EVIDENCE_1_1
        assert _judge_context(self._result(workspace, tmp_path)) == ""

    def test_outcome_metadata_exposes_work_status_and_interruption(self):
        assert _outcome_metadata(OUTCOME) == {
            "bcal_outcome_contract_version": "1.0",
            "bcal_work_status": "absolute_safety_limit",
            "bcal_scenario_completed": False,
            "bcal_interruption_reason": "AbsoluteSafetyLimit",
            "bcal_plan_lifecycle": "InProgress",
            "bcal_validation_state": "Succeeded",
        }
        assert set(_outcome_metadata(None).values()) == {None}
