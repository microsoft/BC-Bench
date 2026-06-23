"""Tests for EvaluationPipeline.execute() template-method orchestration."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from bcbench.config import get_config
from bcbench.dataset import BugFixEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import AgentTimeoutError
from bcbench.results.base import BaseEvaluationResult
from bcbench.types import AgentMetrics, EvaluationContext, ExperimentConfiguration
from tests.conftest import create_evaluation_context


class _StubPipeline(EvaluationPipeline[BugFixEntry]):
    def __init__(self, *, raise_in_evaluate: Exception | None = None, raise_in_run_agent: Exception | None = None) -> None:
        self.raise_in_evaluate = raise_in_evaluate
        self.raise_in_run_agent = raise_in_run_agent
        self.setup_called = False
        self.run_agent_called = False
        self.evaluate_called = False

    def setup_workspace(self, entry: BugFixEntry, repo_path: Path) -> None:
        pass

    def setup(self, context: EvaluationContext[BugFixEntry]) -> None:
        self.setup_called = True

    def run_agent(self, context: EvaluationContext[BugFixEntry], agent_runner: Callable) -> None:
        self.run_agent_called = True
        if self.raise_in_run_agent is not None:
            raise self.raise_in_run_agent
        context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[BugFixEntry]) -> None:
        self.evaluate_called = True
        if self.raise_in_evaluate is not None:
            raise self.raise_in_evaluate


def _noop_runner(_ctx: EvaluationContext[BugFixEntry]) -> tuple[AgentMetrics | None, ExperimentConfiguration | None]:
    return AgentMetrics(execution_time=1.0), ExperimentConfiguration()


def _read_only_result(ctx: EvaluationContext[BugFixEntry]) -> BaseEvaluationResult:
    result_file = ctx.result_dir / f"{ctx.entry.instance_id}{get_config().file_patterns.result_pattern}"
    payload = result_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(payload) == 1, f"Expected one persisted result, got {len(payload)}: {payload}"

    return BaseEvaluationResult.from_json(json.loads(payload[0]))


class _RetryStubPipeline(EvaluationPipeline[BugFixEntry]):
    """Stub that drives the retry loop with per-attempt outcomes.

    ``run_agent_outcomes[i]`` is raised on attempt i when it is an Exception, otherwise the agent
    "succeeds". ``produced_output[i]`` is the value returned by ``agent_produced_output`` after a
    successful attempt i (defaults to True when not supplied).
    """

    def __init__(self, *, attempts: int, run_agent_outcomes: list[Exception | None] | None = None, produced_output: list[bool] | None = None) -> None:
        self._attempts = attempts
        self._run_agent_outcomes = list(run_agent_outcomes or [])
        self._produced_output = list(produced_output or [])
        self.setup_count = 0
        self.run_agent_count = 0
        self.evaluate_count = 0

    def max_agent_attempts(self) -> int:
        return self._attempts

    def setup_workspace(self, entry: BugFixEntry, repo_path: Path) -> None:
        pass

    def setup(self, context: EvaluationContext[BugFixEntry]) -> None:
        self.setup_count += 1

    def run_agent(self, context: EvaluationContext[BugFixEntry], agent_runner: Callable) -> None:
        idx = self.run_agent_count
        self.run_agent_count += 1
        outcome = self._run_agent_outcomes[idx] if idx < len(self._run_agent_outcomes) else None
        if isinstance(outcome, Exception):
            raise outcome
        context.metrics, context.experiment = agent_runner(context)

    def agent_produced_output(self, context: EvaluationContext[BugFixEntry]) -> bool:
        idx = self.run_agent_count - 1
        return self._produced_output[idx] if idx < len(self._produced_output) else True

    def evaluate(self, context: EvaluationContext[BugFixEntry]) -> None:
        self.evaluate_count += 1


class TestExecuteRetry:
    def test_retries_on_timeout_then_succeeds(self, tmp_path):
        ctx = create_evaluation_context(tmp_path)
        timeout = AgentTimeoutError("transient timeout", metrics=AgentMetrics(execution_time=900.0), config=ExperimentConfiguration())
        pipeline = _RetryStubPipeline(attempts=2, run_agent_outcomes=[timeout, None])

        pipeline.execute(ctx, _noop_runner)

        assert pipeline.run_agent_count == 2
        assert pipeline.setup_count == 2  # workspace is reset before the retry
        assert pipeline.evaluate_count == 1

    def test_persists_timeout_after_exhausting_retries(self, tmp_path):
        ctx = create_evaluation_context(tmp_path)
        timeout = AgentTimeoutError("persistent timeout", metrics=AgentMetrics(execution_time=900.0), config=ExperimentConfiguration())
        pipeline = _RetryStubPipeline(attempts=2, run_agent_outcomes=[timeout, timeout])

        pipeline.execute(ctx, _noop_runner)

        assert pipeline.run_agent_count == 2
        assert pipeline.evaluate_count == 0
        assert _read_only_result(ctx).timeout is True

    def test_retries_on_empty_output_then_succeeds(self, tmp_path):
        ctx = create_evaluation_context(tmp_path)
        pipeline = _RetryStubPipeline(attempts=2, produced_output=[False])

        pipeline.execute(ctx, _noop_runner)

        assert pipeline.run_agent_count == 2
        assert pipeline.evaluate_count == 1

    def test_no_retry_when_first_attempt_produces_output(self, tmp_path):
        ctx = create_evaluation_context(tmp_path)
        pipeline = _RetryStubPipeline(attempts=2, produced_output=[True])

        pipeline.execute(ctx, _noop_runner)

        assert pipeline.run_agent_count == 1
        assert pipeline.evaluate_count == 1


class TestExecuteHappyPath:
    def test_runs_setup_then_agent_then_evaluate(self, tmp_path):
        ctx = create_evaluation_context(tmp_path)
        pipeline = _StubPipeline()

        pipeline.execute(ctx, _noop_runner)

        assert pipeline.setup_called
        assert pipeline.run_agent_called
        assert pipeline.evaluate_called


class TestExecuteAgentTimeout:
    def test_persists_timeout_result_and_skips_evaluate(self, tmp_path):
        ctx = create_evaluation_context(tmp_path)
        timeout_metrics = AgentMetrics(execution_time=600.0)
        timeout_config = ExperimentConfiguration(custom_instructions=True)
        pipeline = _StubPipeline(raise_in_run_agent=AgentTimeoutError("test timeout", metrics=timeout_metrics, config=timeout_config))

        pipeline.execute(ctx, _noop_runner)

        assert pipeline.evaluate_called is False
        result = _read_only_result(ctx)
        assert result.timeout is True
        assert result.error_message == "Agent timed out"
        assert result.metrics == timeout_metrics
        assert result.experiment == timeout_config


class TestExecuteEvaluateError:
    def test_unexpected_exceptions_still_propagate(self, tmp_path):
        ctx = create_evaluation_context(tmp_path)
        pipeline = _StubPipeline(raise_in_evaluate=RuntimeError("infra blew up"))

        with pytest.raises(RuntimeError, match="infra blew up"):
            pipeline.execute(ctx, _noop_runner)
