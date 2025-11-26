"""Test mini-agent metrics extraction."""

from unittest.mock import Mock

import pytest

from bcbench.results.bugfix import BugFixResult
from bcbench.types import AgentMetrics
from tests.conftest import create_evaluation_context


class TestMiniAgentMetricsExtraction:
    @pytest.fixture
    def sample_context(self, tmp_path):
        return create_evaluation_context(tmp_path, agent_name="mini-bc-agent", model="azure/gpt-4.1")

    def test_metrics_extraction_with_execution_time_only(self):
        from bcbench.agent.mini.agent import _extract_metrics

        mock_agent = Mock()
        mock_agent.messages = []  # No messages, so no token data

        metrics = _extract_metrics(mock_agent, 120.5)

        assert metrics is not None
        assert metrics.execution_time == 120.5
        assert metrics.prompt_tokens == 0
        assert metrics.completion_tokens == 0

    def test_metrics_extraction_with_token_usage(self):
        from bcbench.agent.mini.agent import _extract_metrics

        mock_agent = Mock()
        mock_agent.messages = [
            {
                "role": "user",
                "content": "test",
            },
            {
                "role": "assistant",
                "content": "response",
                "extra": {
                    "response": {
                        "usage": {
                            "prompt_tokens": 150,
                            "completion_tokens": 50,
                        }
                    }
                },
            },
            {
                "role": "assistant",
                "content": "another response",
                "extra": {
                    "response": {
                        "usage": {
                            "prompt_tokens": 200,
                            "completion_tokens": 75,
                        }
                    }
                },
            },
        ]

        metrics = _extract_metrics(mock_agent, 120.5)

        assert metrics is not None
        assert metrics.execution_time == 120.5
        assert metrics.prompt_tokens == 350  # 150 + 200
        assert metrics.completion_tokens == 125  # 50 + 75

    def test_metrics_extraction_handles_missing_attributes(self):
        from bcbench.agent.mini.agent import _extract_metrics

        mock_agent = Mock()
        # Remove model attribute to simulate missing attributes
        del mock_agent.model

        metrics = _extract_metrics(mock_agent, 45.2)

        # Should return None when agent structure is unexpected
        assert metrics is None

    def test_metrics_extraction_handles_exceptions(self):
        from bcbench.agent.mini.agent import _extract_metrics

        mock_agent = Mock()
        # Make accessing cost raise an exception
        type(mock_agent.model).cost = property(lambda self: (_ for _ in ()).throw(Exception("Test error")))

        metrics = _extract_metrics(mock_agent, 30.0)

        # Should return None when exception occurs
        assert metrics is None

    def test_metrics_flow_to_result_with_tokens(self, sample_context):
        sample_context.metrics = AgentMetrics(
            execution_time=180.5,
            prompt_tokens=5000,
            completion_tokens=1200,
        )

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.instance_id == sample_context.entry.instance_id
        assert result.metrics is not None
        assert result.metrics.execution_time == 180.5
        assert result.metrics.prompt_tokens == 5000
        assert result.metrics.completion_tokens == 1200

    def test_metrics_flow_to_result_without_tokens(self, sample_context):
        sample_context.metrics = AgentMetrics(
            execution_time=180.5,
            prompt_tokens=0,
            completion_tokens=0,
        )

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.instance_id == sample_context.entry.instance_id
        assert result.metrics is not None
        assert result.metrics.execution_time == 180.5
        # Zero tokens should be converted to None in the result
        assert result.metrics.prompt_tokens == 0
        assert result.metrics.completion_tokens == 0

    def test_metrics_flow_with_no_metrics(self, sample_context):
        sample_context.metrics = None

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.metrics is None

    def test_metrics_flow_with_empty_dict(self, sample_context):
        sample_context.metrics = AgentMetrics()

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.metrics is not None
        assert result.metrics.execution_time is None
        assert result.metrics.prompt_tokens is None
        assert result.metrics.completion_tokens is None

    def test_result_preserves_other_fields_with_mini_metrics(self, sample_context):
        sample_context.metrics = AgentMetrics(
            execution_time=95.3,
            prompt_tokens=3500,
            completion_tokens=800,
        )

        result = BugFixResult.create_success(sample_context, "test_patch")

        # Verify metrics
        assert result.metrics is not None
        assert result.metrics.execution_time == 95.3
        assert result.metrics.prompt_tokens == 3500
        assert result.metrics.completion_tokens == 800

        # Verify other fields are still correctly populated
        assert result.instance_id == sample_context.entry.instance_id
        assert result.project == "Shopify"
        assert result.model == "azure/gpt-4.1"
        assert result.agent_name == "mini-bc-agent"
        assert result.resolved is True
        assert result.build is True
        assert result.error_message is None

    def test_metrics_extraction_with_partial_message_data(self):
        from bcbench.agent.mini.agent import _extract_metrics

        mock_agent = Mock()
        mock_agent.messages = [
            {
                "role": "assistant",
                "content": "response without extra",
            },
            {
                "role": "assistant",
                "content": "response with partial extra",
                "extra": {},
            },
            {
                "role": "assistant",
                "content": "response with usage",
                "extra": {
                    "response": {
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 25,
                        }
                    }
                },
            },
        ]

        metrics = _extract_metrics(mock_agent, 45.0)

        assert metrics is not None
        assert metrics.execution_time == 45.0
        assert metrics.prompt_tokens == 100
        assert metrics.completion_tokens == 25

    def test_metrics_extraction_ignores_non_assistant_messages(self):
        from bcbench.agent.mini.agent import _extract_metrics

        mock_agent = Mock()
        mock_agent.messages = [
            {
                "role": "user",
                "content": "user message",
                "extra": {
                    "response": {
                        "usage": {
                            "prompt_tokens": 9999,  # Should be ignored
                            "completion_tokens": 9999,  # Should be ignored
                        }
                    }
                },
            },
            {
                "role": "assistant",
                "content": "assistant message",
                "extra": {
                    "response": {
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 50,
                        }
                    }
                },
            },
        ]

        metrics = _extract_metrics(mock_agent, 30.0)

        assert metrics is not None
        assert metrics.prompt_tokens == 100
        assert metrics.completion_tokens == 50
