import json

import pytest

from bcbench.agent.copilot.metrics import parse_output


def _json_line(data: dict[str, object]) -> str:
    return json.dumps(data)


def test_parse_output_collects_stable_json_metrics_and_final_response():
    output_lines = [
        _json_line({"type": "session.usage_checkpoint", "data": {"totalNanoAiu": 5000000000}}),
        _json_line({"type": "model.call_start", "data": {"turnId": "0"}}),
        _json_line({"type": "assistant.message", "data": {"content": "tool preamble"}}),
        _json_line({"type": "model.call_start", "data": {"turnId": "1"}}),
        _json_line(
            {
                "type": "assistant.message",
                "data": {"content": "done", "phase": "final_answer"},
            }
        ),
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


def test_parse_output_counts_tool_usage_from_stream():
    output_lines = [
        _json_line({"type": "model.call_start", "data": {"turnId": "0"}}),
        _json_line(
            {
                "type": "tool.execution_start",
                "data": {"toolName": "bc_data_query", "arguments": {}},
            }
        ),
        _json_line(
            {
                "type": "tool.execution_start",
                "data": {"toolName": "bc_data_query", "arguments": {}},
            }
        ),
        _json_line(
            {
                "type": "tool.execution_start",
                "data": {"toolName": "task", "arguments": {}},
            }
        ),
        _json_line(
            {
                "type": "tool.execution_start",
                "data": {"toolName": "view", "arguments": {"path": "x"}},
            }
        ),
    ]

    metrics, _ = parse_output(output_lines)

    assert metrics is not None
    assert metrics.tool_usage == {"bc_data_query": 2, "task": 1, "view": 1}


def test_parse_output_sublabels_lsp_operations():
    output_lines = [
        _json_line({"type": "model.call_start", "data": {"turnId": "0"}}),
        _json_line(
            {
                "type": "tool.execution_start",
                "data": {"toolName": "lsp", "arguments": {"operation": "hover"}},
            }
        ),
        _json_line(
            {
                "type": "tool.execution_start",
                "data": {"toolName": "lsp", "arguments": {"operation": "hover"}},
            }
        ),
        _json_line(
            {
                "type": "tool.execution_start",
                "data": {
                    "toolName": "lsp",
                    "arguments": {"operation": "findReferences"},
                },
            }
        ),
    ]

    metrics, _ = parse_output(output_lines)

    assert metrics is not None
    assert metrics.tool_usage == {"lsp:hover": 2, "lsp:findReferences": 1}


def test_parse_output_tool_usage_none_when_no_tools():
    metrics, _ = parse_output([_json_line({"type": "model.call_start", "data": {"turnId": "0"}})])

    assert metrics is not None
    assert metrics.tool_usage is None


def test_parse_output_logs_readable_transcript(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO")

    parse_output(
        [
            _json_line({"type": "assistant.message", "data": {"content": "Inspecting the implementation."}}),
            _json_line({"type": "tool.execution_start", "data": {"toolCallId": "call-1", "toolName": "rg"}}),
            _json_line({"type": "assistant.message", "data": {"content": "Done.", "phase": "final_answer"}}),
        ],
        log_transcript=True,
    )

    assert "Copilot: Inspecting the implementation." in caplog.messages
    assert "Copilot tool: rg" in caplog.messages
    assert "Copilot: Done." in caplog.messages
