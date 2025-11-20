"""Test mini-agent metrics extraction."""

from unittest.mock import Mock, patch

import pytest

from bcbench.dataset import DatasetEntry
from bcbench.results.bugfix import BugFixResult
from bcbench.types import EvaluationCategory, EvaluationContext


class TestMiniAgentMetricsExtraction:
    @pytest.fixture
    def sample_context(self, tmp_path) -> EvaluationContext:
        entry = DatasetEntry(
            instance_id="test__mini-metrics-123",
            repo="test/repo",
            base_commit="a" * 40,
            environment_setup_version="25.1",
            fail_to_pass=[{"codeunitID": 100, "functionName": ["TestMetrics"]}],
            pass_to_pass=[],
            project_paths=["src/app"],
        )
        return EvaluationContext(
            entry=entry,
            repo_path=tmp_path / "repo",
            result_dir=tmp_path / "results",
            container_name="test-container",
            password="test-password",
            username="test-user",
            agent_name="mini-bc-agent",
            model="azure/gpt-4.1",
            category=EvaluationCategory.BUG_FIX,
        )

    def test_metrics_extraction_with_execution_time_only(self):
        from bcbench.agent.mini.agent import _extract_metrics

        mock_agent = Mock()
        mock_agent.messages = []  # No messages, so no token data

        metrics = _extract_metrics(mock_agent, 120.5)

        assert metrics is not None
        assert metrics["agent_execution_time"] == 120.5
        assert metrics["prompt_tokens"] == 0
        assert metrics["completion_tokens"] == 0

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
        assert metrics["agent_execution_time"] == 120.5
        assert metrics["prompt_tokens"] == 350  # 150 + 200
        assert metrics["completion_tokens"] == 125  # 50 + 75

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
        # Simulate metrics returned from mini-agent
        sample_context.agent_metrics = {
            "agent_execution_time": 180.5,
            "prompt_tokens": 5000,
            "completion_tokens": 1200,
        }

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.instance_id == "test__mini-metrics-123"
        assert result.agent_execution_time == 180.5
        assert result.prompt_tokens == 5000
        assert result.completion_tokens == 1200

    def test_metrics_flow_to_result_without_tokens(self, sample_context):
        # Simulate metrics returned from mini-agent with zero tokens
        sample_context.agent_metrics = {
            "agent_execution_time": 180.5,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.instance_id == "test__mini-metrics-123"
        assert result.agent_execution_time == 180.5
        # Zero tokens should be converted to None in the result
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0

    def test_metrics_flow_with_no_metrics(self, sample_context):
        sample_context.agent_metrics = None

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.agent_execution_time is None
        assert result.prompt_tokens is None
        assert result.completion_tokens is None

    def test_metrics_flow_with_empty_dict(self, sample_context):
        sample_context.agent_metrics = {}

        result = BugFixResult.create_success(sample_context, "test_patch")

        assert result.agent_execution_time is None
        assert result.prompt_tokens is None
        assert result.completion_tokens is None

    @pytest.mark.skip(reason="Complex mocking of lazy imports - covered by integration tests")
    @patch("time.time")
    def test_run_mini_agent_tracks_execution_time(self, mock_time, tmp_path):
        from bcbench.agent.mini.agent import run_mini_agent

        # Mock time.time() to return predictable values
        mock_time.side_effect = [100.0, 223.5]  # start and end times

        entry = DatasetEntry(
            instance_id="test_entry",
            repo="test/repo",
            base_commit="a" * 40,
            environment_setup_version="25.1",
            fail_to_pass=[{"codeunitID": 100, "functionName": ["Test"]}],
            pass_to_pass=[],
            project_paths=["src"],
        )

        # Mock the agent and its dependencies
        with patch("bcbench.agent.mini.agent._create_bc_agent_class") as mock_agent_class, patch("bcbench.agent.mini.agent.BCEnvironment") as mock_env_class:
            # Setup mocks
            mock_agent_instance = Mock()
            mock_agent_instance.run.return_value = ("Submitted", "Success")
            mock_agent_instance.model.n_calls = 3
            mock_agent_instance.model.cost = 0.05
            mock_agent_class.return_value = mock_agent_instance

            mock_env = Mock()
            mock_env_class.return_value = mock_env

            # Run the agent
            metrics, _, _ = run_mini_agent(
                entry=entry,
                repo_path=tmp_path / "repo",
                model="azure/gpt-4.1",
                category=EvaluationCategory.BUG_FIX,
                container_name="test",
                password="test",
            )

            # Verify metrics
            assert metrics is not None
            assert "agent_execution_time" in metrics
            assert metrics["agent_execution_time"] == 123.5  # 223.5 - 100.0

    def test_result_preserves_other_fields_with_mini_metrics(self, sample_context):
        sample_context.agent_metrics = {
            "agent_execution_time": 95.3,
            "prompt_tokens": 3500,
            "completion_tokens": 800,
        }

        result = BugFixResult.create_success(sample_context, "test_patch")

        # Verify metrics
        assert result.agent_execution_time == 95.3
        assert result.prompt_tokens == 3500
        assert result.completion_tokens == 800

        # Verify other fields are still correctly populated
        assert result.instance_id == "test__mini-metrics-123"
        assert result.project == "app"
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
        assert metrics["agent_execution_time"] == 45.0
        assert metrics["prompt_tokens"] == 100
        assert metrics["completion_tokens"] == 25

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
        assert metrics["prompt_tokens"] == 100
        assert metrics["completion_tokens"] == 50
