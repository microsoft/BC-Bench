"""Test the complete metrics flow from parsing to result creation."""

import json

import pytest

from bcbench.agent.copilot.metrics import parse_output
from bcbench.results.bugfix import BugFixResult
from bcbench.types import AgentHarness, AgentMetrics
from tests.conftest import create_evaluation_context


def _parse_full_metrics(
    *,
    execution_time: float,
    llm_duration: float,
    ai_credits: float = 1.25,
    turn_count: int = 2,
) -> AgentMetrics | None:
    output_lines = [
        json.dumps({"type": "session.usage_checkpoint", "data": {"totalNanoAiu": ai_credits * 1_000_000_000}}),
        *[json.dumps({"type": "model.call_start", "data": {"turnId": str(turn)}}) for turn in range(turn_count)],
        json.dumps(
            {
                "type": "result",
                "usage": {
                    "sessionDurationMs": execution_time * 1000,
                    "totalApiDurationMs": llm_duration * 1000,
                },
            }
        ),
    ]
    metrics, _ = parse_output(output_lines)
    return metrics


class TestCopilotMetricsToResultFlow:
    @pytest.fixture
    def sample_context(self, tmp_path):
        return create_evaluation_context(tmp_path, agent_name=AgentHarness.COPILOT, model="gpt-4o")

    def test_full_metrics_flow_to_success_result(self, sample_context):
        sample_context.metrics = _parse_full_metrics(
            execution_time=225.2,
            llm_duration=34.5,
        )

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.instance_id == sample_context.entry.instance_id
        assert result.resolved is True
        assert result.project == "Shopify"
        assert result.build is True
        assert result.metrics is not None
        assert result.metrics.execution_time == 225.2
        assert result.metrics.llm_duration == 34.5
        assert result.metrics.ai_credits == 1.25
        assert result.metrics.turn_count == 2
        assert result.metrics.prompt_tokens is None
        assert result.metrics.completion_tokens is None

    def test_metrics_flow_with_partial_metrics(self, sample_context):
        sample_context.metrics, _ = parse_output(
            [
                json.dumps(
                    {
                        "type": "result",
                        "usage": {"sessionDurationMs": 90000},
                    }
                )
            ]
        )

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.metrics is not None
        assert result.metrics.execution_time == 90.0
        assert result.metrics.llm_duration is None
        assert result.metrics.prompt_tokens is None
        assert result.metrics.completion_tokens is None

    def test_metrics_flow_with_no_metrics(self, sample_context):
        sample_context.metrics, _ = parse_output([json.dumps({"type": "assistant.idle", "data": {}})])

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.metrics is None

    def test_metrics_flow_to_test_failure_result(self, sample_context):
        sample_context.metrics = _parse_full_metrics(
            execution_time=135.5,
            llm_duration=45.0,
        )

        result = BugFixResult.create_test_failure(sample_context, "test_patch")

        assert result.resolved is False
        assert result.build is True
        assert result.error_message == "Tests failed"
        assert result.metrics is not None
        assert result.metrics.execution_time == 135.5
        assert result.metrics.prompt_tokens is None
        assert result.metrics.completion_tokens is None

    def test_metrics_flow_to_build_failure_result(self, sample_context):
        sample_context.metrics = _parse_full_metrics(
            execution_time=310.3,
            llm_duration=80.0,
        )

        result = BugFixResult.create_build_failure(sample_context, "test_patch", "Build failed: src/app")

        assert result.resolved is False
        assert result.build is False
        assert result.error_message == "Build failed: src/app"
        assert result.metrics is not None
        assert result.metrics.execution_time == 310.3
        assert result.metrics.prompt_tokens is None
        assert result.metrics.completion_tokens is None

    def test_context_without_agent_metrics_set(self, sample_context):
        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.metrics is None

    def test_context_with_empty_metrics_dict(self, sample_context):
        sample_context.metrics = AgentMetrics()

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.metrics is not None
        assert result.metrics.execution_time is None
        assert result.metrics.prompt_tokens is None
        assert result.metrics.completion_tokens is None

    def test_metrics_with_non_integer_tokens_are_converted(self, sample_context):
        sample_context.metrics = AgentMetrics(
            execution_time=150.5,
            prompt_tokens=12500,
            completion_tokens=3200,
        )

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.metrics is not None
        assert isinstance(result.metrics.prompt_tokens, int)
        assert isinstance(result.metrics.completion_tokens, int)
        assert result.metrics.prompt_tokens == 12500
        assert result.metrics.completion_tokens == 3200

    def test_metrics_flow_preserves_other_result_fields(self, sample_context):
        sample_context.metrics = _parse_full_metrics(
            execution_time=60.0,
            llm_duration=20.0,
        )

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.metrics is not None
        assert result.metrics.execution_time == 60.0
        assert result.metrics.prompt_tokens is None
        assert result.metrics.completion_tokens is None
        assert result.instance_id == sample_context.entry.instance_id
        assert result.project == "Shopify"
        assert result.model == "gpt-4o"
        assert result.agent_name == AgentHarness.COPILOT
        assert result.resolved is True
        assert result.build is True
        assert result.error_message is None
