"""Tests for Claude Code metrics parsing."""

import json
from pathlib import Path

import pytest

from bcbench.agent.claude.metrics import (
    encode_project_dir,
    find_session_transcript,
    parse_metrics,
    parse_tool_usage_from_transcript,
)


class TestClaudeCodeMetricsParsing:
    def test_parse_metrics_full_output(self, tmp_path):
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

        metrics = parse_metrics(data, session_cwd=tmp_path)

        assert metrics is not None
        assert metrics.execution_time == pytest.approx(2.814, rel=1e-3)
        assert metrics.llm_duration == pytest.approx(4.819, rel=1e-3)
        assert metrics.turn_count == 1
        assert metrics.prompt_tokens == 2 + 4974 + 12673  # input + cache_creation + cache_read
        assert metrics.completion_tokens == 5
        assert metrics.tool_usage is None  # Not parsed from JSON

    def test_parse_metrics_minimal_output(self, tmp_path):
        data = {"type": "result", "duration_ms": 1000, "num_turns": 3}

        metrics = parse_metrics(data, session_cwd=tmp_path)

        assert metrics is not None
        assert metrics.execution_time == 1.0
        assert metrics.turn_count == 3
        assert metrics.llm_duration is None
        assert metrics.prompt_tokens is None
        assert metrics.completion_tokens is None

    def test_parse_metrics_with_usage_no_cache(self, tmp_path):
        data = {
            "type": "result",
            "duration_ms": 5000,
            "duration_api_ms": 3000,
            "num_turns": 5,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

        metrics = parse_metrics(data, session_cwd=tmp_path)

        assert metrics is not None
        assert metrics.execution_time == 5.0
        assert metrics.llm_duration == 3.0
        assert metrics.turn_count == 5
        assert metrics.prompt_tokens == 100  # No cache tokens
        assert metrics.completion_tokens == 50

    def test_parse_metrics_empty_dict(self, tmp_path):
        metrics = parse_metrics({}, session_cwd=tmp_path)

        assert metrics is None  # No metrics fields present

    def test_parse_metrics_only_duration(self, tmp_path):
        data = {"duration_ms": 12345}

        metrics = parse_metrics(data, session_cwd=tmp_path)

        assert metrics is not None
        assert metrics.execution_time == pytest.approx(12.345, rel=1e-3)
        assert metrics.llm_duration is None
        assert metrics.turn_count is None
        assert metrics.prompt_tokens is None
        assert metrics.completion_tokens is None

    def test_parse_metrics_with_model_usage(self, tmp_path):
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

        metrics = parse_metrics(data, session_cwd=tmp_path)

        assert metrics is not None
        assert metrics.execution_time == pytest.approx(175.011, rel=1e-3)
        assert metrics.llm_duration == pytest.approx(118.584, rel=1e-3)
        assert metrics.turn_count == 14
        assert metrics.prompt_tokens == 41 + 22439 + 246700
        assert metrics.completion_tokens == 1909


class TestParseToolUsageFromTranscript:
    def _write_transcript(self, path, entries):
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

    def test_counts_tool_use_blocks(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        self._write_transcript(
            transcript,
            [
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Glob"}]}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
            ],
        )

        assert parse_tool_usage_from_transcript(transcript) == {"Read": 2, "Glob": 1}

    def test_counts_mcp_tool_names(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        self._write_transcript(
            transcript,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "mcp__filesystem__write_file"},
                            {"type": "tool_use", "name": "Read"},
                        ]
                    },
                },
            ],
        )

        assert parse_tool_usage_from_transcript(transcript) == {"mcp__filesystem__write_file": 1, "Read": 1}

    def test_ignores_malformed_lines(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(
            "not json\n" + json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}}) + "\n\n",
            encoding="utf-8",
        )

        assert parse_tool_usage_from_transcript(transcript) == {"Read": 1}

    def test_returns_empty_when_no_tool_use(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        self._write_transcript(
            transcript,
            [{"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}],
        )

        assert parse_tool_usage_from_transcript(transcript) == {}


class TestEncodeProjectDir:
    def test_windows_path(self):
        assert encode_project_dir("C:\\depot\\BC-Bench") == "C--depot-BC-Bench"

    def test_posix_path(self):
        assert encode_project_dir("/home/user/foo") == "-home-user-foo"


class TestFindSessionTranscript:
    def test_returns_path_when_present(self, tmp_path, monkeypatch):
        cwd = tmp_path / "proj"
        cwd.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        session_dir = tmp_path / ".claude" / "projects" / encode_project_dir(cwd)
        session_dir.mkdir(parents=True)
        session_file = session_dir / "abc.jsonl"
        session_file.write_text("", encoding="utf-8")

        assert find_session_transcript("abc", cwd) == session_file

    def test_returns_none_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        assert find_session_transcript("abc", tmp_path / "proj") is None


class TestParseMetricsWithTranscript:
    def test_parse_metrics_with_session_transcript(self, tmp_path, monkeypatch):
        cwd = tmp_path / "proj"
        cwd.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        session_dir = tmp_path / ".claude" / "projects" / encode_project_dir(cwd)
        session_dir.mkdir(parents=True)
        (session_dir / "sess-1.jsonl").write_text(
            json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}})
            + "\n"
            + json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit"}]}})
            + "\n"
            + json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit"}]}})
            + "\n",
            encoding="utf-8",
        )

        data = {"type": "result", "duration_ms": 5000, "num_turns": 3, "session_id": "sess-1"}
        metrics = parse_metrics(data, session_cwd=cwd)

        assert metrics is not None
        assert metrics.tool_usage == {"Read": 1, "Edit": 2}
        assert metrics.execution_time == 5.0

    def test_parse_metrics_without_session_id(self, tmp_path):
        data = {"type": "result", "duration_ms": 5000, "num_turns": 3}

        metrics = parse_metrics(data, session_cwd=tmp_path)

        assert metrics is not None
        assert metrics.tool_usage is None

    def test_parse_metrics_missing_transcript(self, tmp_path):
        data = {"type": "result", "duration_ms": 5000, "num_turns": 3, "session_id": "missing"}

        metrics = parse_metrics(data, session_cwd=tmp_path)

        assert metrics is not None
        assert metrics.tool_usage is None
