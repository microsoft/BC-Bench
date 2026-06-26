"""Tests for EvaluationPipeline.execute() template-method orchestration."""

import json
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.commands.evaluate import MockEvaluationPipeline
from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry, BugFixEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import AgentTimeoutError
from bcbench.results.base import BaseEvaluationResult
from bcbench.types import AgentMetrics, EvaluationCategory, EvaluationContext, ExperimentConfiguration
from tests.conftest import create_codereview_entry, create_dataset_entry, create_evaluation_context, create_hello_world_entry, create_nl2al_entry


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


def _entry_for_category(category: EvaluationCategory) -> BaseDatasetEntry:
    match category:
        case EvaluationCategory.CODE_REVIEW:
            return create_codereview_entry()
        case EvaluationCategory.NL2AL:
            return create_nl2al_entry()
        case EvaluationCategory.HELLO_WORLD:
            return create_hello_world_entry()
        case _:
            return create_dataset_entry()


class TestMockPipelineCoversAllCategories:
    # Guards the CI mock-evaluation job: a newly added category must be handled here or this fails fast in unit tests.
    @pytest.mark.parametrize("category", list(EvaluationCategory))
    def test_every_category_produces_valid_result(self, tmp_path, category):
        entry = _entry_for_category(category)
        ctx = create_evaluation_context(tmp_path, entry=entry, category=category)
        pipeline = MockEvaluationPipeline()

        # Force each scenario deterministically so every branch is exercised, not just a random one.
        for pick in (lambda seq: seq[0], lambda seq: seq[-1]):
            with patch("bcbench.commands.evaluate.random.choice", pick):
                pipeline.evaluate(ctx)

        result_file = ctx.result_dir / f"{entry.instance_id}{get_config().file_patterns.result_pattern}"
        results = [BaseEvaluationResult.from_json(json.loads(line)) for line in result_file.read_text(encoding="utf-8").splitlines()]
        assert {r.category for r in results} == {category}
        assert all(r.instance_id == entry.instance_id for r in results)
