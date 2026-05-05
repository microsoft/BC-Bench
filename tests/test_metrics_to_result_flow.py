"""Test the complete metrics flow from parsing to result creation."""

import pytest

from bcbench.agent.copilot.metrics import parse_metrics
from bcbench.results.bugfix import BugFixResult
from bcbench.types import AgentMetrics
from tests.conftest import create_evaluation_context


class TestCopilotMetricsToResultFlow:
    @pytest.fixture
    def sample_context(self, tmp_path):
        return create_evaluation_context(tmp_path, agent_name="copilot-cli", model="gpt-4o")

    def test_full_metrics_flow_to_success_result(self, sample_context):
        output_lines = [
            "Total session time:     3m 45.2s\n",
            "Breakdown by AI model:\n",
            "   gpt-4o    100.5k in, 2.3k out\n",
        ]
        metrics = parse_metrics(output_lines)

        sample_context.metrics = metrics

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.instance_id == sample_context.entry.instance_id
        assert result.resolved is True
        assert result.project == "Shopify"
        assert result.build is True
        assert result.metrics is not None
        assert result.metrics.execution_time == 225.2
        assert result.metrics.prompt_tokens == 100500
        assert result.metrics.completion_tokens == 2300

    def test_metrics_flow_with_seconds_only_wall_time(self, sample_context):
        output_lines = [
            "Total session time:     45.7s\n",
            "Breakdown by AI model:\n",
            "   gpt-4o    50k in, 1k out\n",
        ]
        metrics = parse_metrics(output_lines)
        sample_context.metrics = metrics

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.metrics is not None
        assert result.metrics.execution_time == 45.7
        assert result.metrics.prompt_tokens == 50000
        assert result.metrics.completion_tokens == 1000

    def test_metrics_flow_with_partial_metrics(self, sample_context):
        output_lines = ["Total session time: 1m 30s\n"]
        metrics = parse_metrics(output_lines)
        sample_context.metrics = metrics

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.metrics is not None
        assert result.metrics.execution_time == 90.0
        assert result.metrics.prompt_tokens is None
        assert result.metrics.completion_tokens is None

    def test_metrics_flow_with_no_metrics(self, sample_context):
        output_lines = ["Some output without metrics\n"]
        metrics = parse_metrics(output_lines)
        sample_context.metrics = metrics

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.metrics is None

    def test_metrics_flow_to_test_failure_result(self, sample_context):
        output_lines = [
            "Total session time:     2m 15.5s\n",
            "Breakdown by AI model:\n",
            "   gpt-4o    75.2k in, 1.8k out\n",
        ]
        metrics = parse_metrics(output_lines)
        sample_context.metrics = metrics

        result = BugFixResult.create_test_failure(sample_context, "test_patch")

        assert result.resolved is False
        assert result.build is True
        assert result.error_message == "Tests failed"
        assert result.metrics is not None
        assert result.metrics.execution_time == 135.5
        assert result.metrics.prompt_tokens == 75200
        assert result.metrics.completion_tokens == 1800

    def test_metrics_flow_to_build_failure_result(self, sample_context):
        output_lines = [
            "Total session time:     5m 10.3s\n",
            "Breakdown by AI model:\n",
            "   gpt-4o    200k in, 5k out\n",
        ]
        metrics = parse_metrics(output_lines)
        sample_context.metrics = metrics

        result = BugFixResult.create_build_failure(sample_context, "test_patch", "Build failed: src/app")

        assert result.resolved is False
        assert result.build is False
        assert result.error_message == "Build failed: src/app"
        assert result.metrics is not None
        assert result.metrics.execution_time == 310.3
        assert result.metrics.prompt_tokens == 200000
        assert result.metrics.completion_tokens == 5000

    def test_metrics_flow_with_real_copilot_output(self, sample_context):
        output_lines = [
            "  ✓ Search for code pattern\n",
            "     $ Get-ChildItem -Path C:\\temp\\repo -Recurse -Filter *.al\n",
            "     ↪ 10 lines...\n",
            "\n",
            "  Total usage est:        1 Premium request\n",
            "  API time spent:         45.2s\n",
            "  Total session time:     4m 32.8s\n",
            "  Total code changes:     +5 -2\n",
            "  Breakdown by AI model:\n",
            "   gpt-4o    125.5k in, 3.6k out, 0 cached\n",
        ]
        metrics = parse_metrics(output_lines)
        sample_context.metrics = metrics

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.metrics is not None
        assert result.metrics.execution_time == 272.8
        assert result.metrics.prompt_tokens == 125500
        assert result.metrics.completion_tokens == 3600

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
        # Simulate metrics with float values (from k conversion)
        sample_context.metrics = AgentMetrics(
            execution_time=150.5,
            prompt_tokens=12500,  # Int from 12.5k
            completion_tokens=3200,  # Int from 3.2k
        )

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.metrics is not None
        assert isinstance(result.metrics.prompt_tokens, int)
        assert isinstance(result.metrics.completion_tokens, int)
        assert result.metrics.prompt_tokens == 12500
        assert result.metrics.completion_tokens == 3200

    def test_metrics_flow_preserves_other_result_fields(self, sample_context):
        output_lines = [
            "Total session time:     1m 0s\n",
            "Breakdown by AI model:\n",
            "   gpt-4o    10k in, 500 out\n",
        ]
        metrics = parse_metrics(output_lines)
        sample_context.metrics = metrics

        result = BugFixResult.create_success(sample_context, "test_patch")

        # Verify metrics are present
        assert result.metrics is not None
        assert result.metrics.execution_time == 60.0
        assert result.metrics.prompt_tokens == 10000
        assert result.metrics.completion_tokens == 500

        # Verify other fields are still correctly populated
        assert result.instance_id == sample_context.entry.instance_id
        assert result.project == "Shopify"
        assert result.model == "gpt-4o"
        assert result.agent_name == "copilot-cli"
        assert result.resolved is True
        assert result.build is True
        assert result.error_message is None
