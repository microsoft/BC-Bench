from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from bcbench.agent.copilot.metrics import parse_metrics_from_sdk_events


class SessionEventType(Enum):
    ASSISTANT_TURN_START = "assistant.turn_start"
    ASSISTANT_USAGE = "assistant.usage"
    TOOL_EXECUTION_START = "tool.execution_start"
    SESSION_IDLE = "session.idle"


@dataclass
class EventData:
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration: float | None = None
    tool_name: str | None = None


@dataclass
class SessionEvent:
    type: SessionEventType
    data: EventData
    id: UUID
    timestamp: datetime


def create_event(event_type: SessionEventType, **data_kwargs) -> SessionEvent:
    return SessionEvent(
        type=event_type,
        data=EventData(**data_kwargs),
        id=uuid4(),
        timestamp=datetime.now(),
    )


def test_parse_metrics_from_sdk_events_with_full_data():
    events = [
        create_event(SessionEventType.ASSISTANT_TURN_START),
        create_event(SessionEventType.ASSISTANT_USAGE, input_tokens=1000, output_tokens=500, duration=5000),
        create_event(SessionEventType.TOOL_EXECUTION_START, tool_name="view"),
        create_event(SessionEventType.ASSISTANT_TURN_START),
        create_event(SessionEventType.ASSISTANT_USAGE, input_tokens=2000, output_tokens=800, duration=7000),
        create_event(SessionEventType.TOOL_EXECUTION_START, tool_name="edit"),
        create_event(SessionEventType.TOOL_EXECUTION_START, tool_name="view"),
        create_event(SessionEventType.SESSION_IDLE),
    ]

    execution_time = 120.5
    result = parse_metrics_from_sdk_events(events, execution_time)

    assert result is not None
    assert result.execution_time == 120.5
    assert result.prompt_tokens == 3000  # 1000 + 2000
    assert result.completion_tokens == 1300  # 500 + 800
    assert result.llm_duration == 12.0  # (5000 + 7000) / 1000
    assert result.turn_count == 2
    assert result.tool_usage == {"view": 2, "edit": 1}


def test_parse_metrics_from_sdk_events_with_partial_data():
    events = [
        create_event(SessionEventType.ASSISTANT_TURN_START),
        create_event(SessionEventType.ASSISTANT_USAGE, input_tokens=1000, output_tokens=500),  # No duration
        create_event(SessionEventType.SESSION_IDLE),
    ]

    execution_time = 60.0
    result = parse_metrics_from_sdk_events(events, execution_time)

    assert result is not None
    assert result.execution_time == 60.0
    assert result.prompt_tokens == 1000
    assert result.completion_tokens == 500
    assert result.llm_duration is None  # No duration data
    assert result.turn_count == 1
    assert result.tool_usage is None


def test_parse_metrics_from_sdk_events_with_no_usage_data():
    events = [
        create_event(SessionEventType.ASSISTANT_TURN_START),
        create_event(SessionEventType.TOOL_EXECUTION_START, tool_name="bash"),
        create_event(SessionEventType.SESSION_IDLE),
    ]

    execution_time = 30.0
    result = parse_metrics_from_sdk_events(events, execution_time)

    assert result is not None
    assert result.execution_time == 30.0
    assert result.prompt_tokens is None
    assert result.completion_tokens is None
    assert result.llm_duration is None
    assert result.turn_count == 1
    assert result.tool_usage == {"bash": 1}


def test_parse_metrics_from_sdk_events_with_empty_events():
    events = []
    execution_time = 10.0
    result = parse_metrics_from_sdk_events(events, execution_time)

    assert result is None


def test_parse_metrics_from_sdk_events_with_only_idle_event():
    events = [
        create_event(SessionEventType.SESSION_IDLE),
    ]

    execution_time = 5.0
    result = parse_metrics_from_sdk_events(events, execution_time)

    assert result is None


def test_parse_metrics_from_sdk_events_multiple_tool_calls():
    events = [
        create_event(SessionEventType.ASSISTANT_TURN_START),
        create_event(SessionEventType.TOOL_EXECUTION_START, tool_name="view"),
        create_event(SessionEventType.TOOL_EXECUTION_START, tool_name="grep"),
        create_event(SessionEventType.TOOL_EXECUTION_START, tool_name="view"),
        create_event(SessionEventType.TOOL_EXECUTION_START, tool_name="edit"),
        create_event(SessionEventType.TOOL_EXECUTION_START, tool_name="view"),
        create_event(SessionEventType.ASSISTANT_USAGE, input_tokens=5000, output_tokens=1000, duration=10000),
        create_event(SessionEventType.SESSION_IDLE),
    ]

    execution_time = 150.0
    result = parse_metrics_from_sdk_events(events, execution_time)

    assert result is not None
    assert result.execution_time == 150.0
    assert result.prompt_tokens == 5000
    assert result.completion_tokens == 1000
    assert result.llm_duration == 10.0
    assert result.turn_count == 1
    assert result.tool_usage == {"view": 3, "grep": 1, "edit": 1}


def test_parse_metrics_from_sdk_events_zero_tokens():
    events = [
        create_event(SessionEventType.ASSISTANT_TURN_START),
        create_event(SessionEventType.ASSISTANT_USAGE, input_tokens=0, output_tokens=0, duration=1000),
        create_event(SessionEventType.SESSION_IDLE),
    ]

    execution_time = 10.0
    result = parse_metrics_from_sdk_events(events, execution_time)

    # Should return metrics even with 0 tokens because we have turn_count
    assert result is not None
    assert result.execution_time == 10.0
    assert result.prompt_tokens is None  # 0 tokens converted to None
    assert result.completion_tokens is None  # 0 tokens converted to None
    assert result.llm_duration == 1.0  # Duration is still captured
    assert result.turn_count == 1
