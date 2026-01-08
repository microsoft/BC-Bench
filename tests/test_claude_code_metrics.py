"""Tests for Claude Code metrics parsing."""

import pytest

from bcbench.agent.claude.metrics import parse_metrics


class TestClaudeCodeMetricsParsing:
    def test_parse_metrics_full_output(self):
        data = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 2814,
            "duration_api_ms": 4819,
            "num_turns": 1,
            "result": "2",
            "session_id": "0dd1b90a-f477-431f-a278-f3079e4f795f",
            "total_cost_usd": 0.024096399999999997,
            "usage": {
                "input_tokens": 2,
                "cache_creation_input_tokens": 4974,
                "cache_read_input_tokens": 12673,
                "output_tokens": 5,
                "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
                "service_tier": "standard",
            },
        }

        metrics = parse_metrics(data)

        assert metrics is not None
        assert metrics.execution_time == pytest.approx(2.814, rel=1e-3)
        assert metrics.llm_duration == pytest.approx(4.819, rel=1e-3)
        assert metrics.turn_count == 1
        assert metrics.prompt_tokens == 2 + 4974 + 12673  # input + cache_creation + cache_read
        assert metrics.completion_tokens == 5
        assert metrics.tool_usage is None  # Not parsed from JSON

    def test_parse_metrics_minimal_output(self):
        data = {"type": "result", "duration_ms": 1000, "num_turns": 3}

        metrics = parse_metrics(data)

        assert metrics is not None
        assert metrics.execution_time == 1.0
        assert metrics.turn_count == 3
        assert metrics.llm_duration is None
        assert metrics.prompt_tokens is None
        assert metrics.completion_tokens is None

    def test_parse_metrics_with_usage_no_cache(self):
        data = {
            "type": "result",
            "duration_ms": 5000,
            "duration_api_ms": 3000,
            "num_turns": 5,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

        metrics = parse_metrics(data)

        assert metrics is not None
        assert metrics.execution_time == 5.0
        assert metrics.llm_duration == 3.0
        assert metrics.turn_count == 5
        assert metrics.prompt_tokens == 100  # No cache tokens
        assert metrics.completion_tokens == 50

    def test_parse_metrics_empty_dict(self):
        metrics = parse_metrics({})

        assert metrics is None  # No metrics fields present

    def test_parse_metrics_only_duration(self):
        data = {"duration_ms": 12345}

        metrics = parse_metrics(data)

        assert metrics is not None
        assert metrics.execution_time == pytest.approx(12.345, rel=1e-3)
        assert metrics.llm_duration is None
        assert metrics.turn_count is None
        assert metrics.prompt_tokens is None
        assert metrics.completion_tokens is None

    def test_parse_metrics_with_model_usage(self):
        # Real-world sample with modelUsage breakdown (multi-model scenario)
        # We parse from top-level usage only, modelUsage is per-model breakdown (not parsed)
        data = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 175011,
            "duration_api_ms": 118584,
            "num_turns": 14,
            "result": "Fix Complete",
            "session_id": "89b1580d-e994-49bd-8908-23fdde122e73",
            "total_cost_usd": 0.29006764999999995,
            "usage": {
                "input_tokens": 41,
                "cache_creation_input_tokens": 22439,
                "cache_read_input_tokens": 246700,
                "output_tokens": 1909,
            },
            "modelUsage": {
                "claude-haiku-4-5-20251001": {"inputTokens": 48287, "outputTokens": 8017},
                "claude-sonnet-4-5-20250929": {"inputTokens": 3, "outputTokens": 324},
            },
        }

        metrics = parse_metrics(data)

        assert metrics is not None
        assert metrics.execution_time == pytest.approx(175.011, rel=1e-3)
        assert metrics.llm_duration == pytest.approx(118.584, rel=1e-3)
        assert metrics.turn_count == 14
        assert metrics.prompt_tokens == 41 + 22439 + 246700
        assert metrics.completion_tokens == 1909
