import json
from collections import Counter
from collections.abc import Sequence

from bcbench.logger import get_logger
from bcbench.types import AgentMetrics

logger = get_logger(__name__)


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _milliseconds_to_seconds(value: object) -> float | None:
    milliseconds = _as_float(value)
    return None if milliseconds is None else milliseconds / 1000.0


def _tool_label(block: dict) -> str | None:
    tool_name = block.get("name")
    if not isinstance(tool_name, str) or not tool_name:
        return None
    if tool_name == "lsp":
        tool_input = block.get("input")
        if isinstance(tool_input, dict) and isinstance(tool_input.get("operation"), str):
            return f"lsp:{tool_input['operation']}"
    return tool_name


def parse_stream_output(output_lines: Sequence[str], *, log_transcript: bool = False) -> tuple[AgentMetrics | None, str | None]:
    execution_time: float | None = None
    llm_duration: float | None = None
    turn_count: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tool_usage: Counter[str] = Counter()
    final_response: str | None = None
    # The final text is emitted in both AssistantMessage and ResultMessage:
    # https://code.claude.com/docs/en/agent-sdk/agent-loop#the-loop-at-a-glance
    last_assistant_message: str | None = None

    for line_number, line in enumerate(output_lines, start=1):
        if not line.strip():
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            logger.warning(f"Skipping invalid JSON from Claude Code output at line {line_number}: {error}")
            continue

        if not isinstance(event, dict):
            logger.warning(f"Skipping non-object JSON from Claude Code output at line {line_number}")
            continue

        match event.get("type"):
            case "assistant":
                message = event.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        match block.get("type"):
                            case "text":
                                text = block.get("text")
                                if log_transcript and isinstance(text, str) and text.strip():
                                    last_assistant_message = text.strip()
                                    logger.info("Claude Code: %s", last_assistant_message)
                            case "tool_use":
                                if label := _tool_label(block):
                                    tool_usage[label] += 1
                                    if log_transcript:
                                        logger.info("Claude Code tool: %s", label)
            case "result":
                execution_time = _milliseconds_to_seconds(event.get("duration_ms"))
                llm_duration = _milliseconds_to_seconds(event.get("duration_api_ms"))
                turn_count = _as_int(event.get("num_turns"))

                usage = event.get("usage")
                if isinstance(usage, dict):
                    prompt_token_parts = [
                        _as_int(usage.get("input_tokens")),
                        _as_int(usage.get("cache_creation_input_tokens")),
                        _as_int(usage.get("cache_read_input_tokens")),
                    ]
                    if any(value is not None for value in prompt_token_parts):
                        prompt_tokens = sum(value or 0 for value in prompt_token_parts)
                    completion_tokens = _as_int(usage.get("output_tokens"))

                result_text = event.get("result")
                if isinstance(result_text, str) and result_text:
                    final_response = result_text
                    if log_transcript and result_text.strip() != last_assistant_message:
                        logger.info("Claude Code: %s", result_text.strip())

    metrics = None
    if execution_time is not None or llm_duration is not None or turn_count is not None or prompt_tokens is not None or completion_tokens is not None or tool_usage:
        metrics = AgentMetrics(
            execution_time=execution_time,
            llm_duration=llm_duration,
            turn_count=turn_count,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            tool_usage=dict(tool_usage) or None,
        )
    else:
        logger.warning("No metrics found in Claude Code JSON output")

    return metrics, final_response
