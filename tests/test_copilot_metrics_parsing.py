import json

import pytest

from bcbench.agent.copilot.metrics import parse_mcp_server_status, parse_output
from bcbench.types import McpServerStatus


def _json_line(data: dict[str, object]) -> str:
    return json.dumps(data)


def test_parse_output_collects_stable_json_metrics_and_final_response():
    output_lines = [
        _json_line({"type": "session.usage_checkpoint", "data": {"totalNanoAiu": 5000000000}}),
        _json_line({"type": "model.call_start", "data": {"turnId": "0"}}),
        _json_line({"type": "assistant.message", "data": {"content": "tool preamble"}}),
        _json_line({"type": "model.call_start", "data": {"turnId": "1"}}),
        _json_line({"type": "assistant.message", "data": {"content": "done", "phase": "final_answer"}}),
        _json_line({"type": "session.usage_checkpoint", "data": {"totalNanoAiu": 10827400000}}),
        _json_line(
            {
                "type": "result",
                "usage": {
                    "totalApiDurationMs": 3555,
                    "sessionDurationMs": 8632,
                },
            }
        ),
    ]

    metrics, response = parse_output(output_lines)

    assert metrics is not None
    assert metrics.execution_time == pytest.approx(8.632)
    assert metrics.llm_duration == pytest.approx(3.555)
    assert metrics.ai_credits == pytest.approx(10.8274)
    assert metrics.turn_count == 2
    assert metrics.prompt_tokens is None
    assert metrics.completion_tokens is None
    assert response == "done"


def test_parse_output_skips_invalid_json(caplog: pytest.LogCaptureFixture):
    metrics, _ = parse_output(
        [
            "not json",
            _json_line(
                {
                    "type": "result",
                    "usage": {"sessionDurationMs": 1000},
                }
            ),
        ]
    )

    assert metrics is not None
    assert metrics.execution_time == 1.0
    assert "Skipping invalid JSON from Copilot CLI output at line 1" in caplog.text


def test_parse_output_uses_last_message_when_no_final_answer():
    _, response = parse_output(
        [
            _json_line({"type": "assistant.message", "data": {"content": "first"}}),
            _json_line({"type": "assistant.message", "data": {"content": "second"}}),
        ]
    )

    assert response == "second"


def test_parse_output_empty():
    assert parse_output([]) == (None, None)


def test_parse_output_without_metrics():
    metrics, response = parse_output([_json_line({"type": "assistant.message", "data": {"content": "done"}})])

    assert metrics is None
    assert response == "done"


def test_parse_mcp_server_status_prefers_settled_roster_over_transitions():
    output_lines = [
        _json_line({"type": "session.mcp_server_status_changed", "data": {"serverName": "altool", "status": "pending"}}),
        _json_line({"type": "session.mcp_server_status_changed", "data": {"serverName": "altool", "status": "connected"}}),
        _json_line(
            {
                "type": "session.mcp_servers_loaded",
                "data": {
                    "servers": [
                        {"name": "altool", "status": "connected"},
                        {"name": "github-mcp-server", "status": "disabled", "source": "builtin"},
                    ]
                },
            }
        ),
    ]

    assert parse_mcp_server_status(output_lines) == [
        McpServerStatus(name="altool", status="connected"),
        McpServerStatus(name="github-mcp-server", status="disabled"),
    ]


def test_parse_mcp_server_status_captures_spawn_failure_error():
    error = "failed to spawn MCP server process: program not found: program not found"
    output_lines = [
        _json_line({"type": "session.mcp_server_status_changed", "data": {"serverName": "altool", "status": "pending"}}),
        _json_line({"type": "session.mcp_server_status_changed", "data": {"serverName": "altool", "status": "failed", "error": error}}),
    ]

    assert parse_mcp_server_status(output_lines) == [McpServerStatus(name="altool", status="failed", error=error)]


def test_parse_mcp_server_status_without_mcp_events():
    assert parse_mcp_server_status([_json_line({"type": "assistant.message", "data": {"content": "done"}})]) == []
