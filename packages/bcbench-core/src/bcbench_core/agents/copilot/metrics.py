import json
import logging
from collections import Counter
from collections.abc import Sequence

from bcbench_core.types import AgentMetrics

logger = logging.getLogger(__name__)
NANO_AIU_PER_AI_CREDIT = 1_000_000_000


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _milliseconds_to_seconds(value: object) -> float | None:
    milliseconds = _as_float(value)
    return None if milliseconds is None else milliseconds / 1000.0


def _tool_label(data: dict) -> str | None:
    tool_name = data.get("toolName")
    if not isinstance(tool_name, str) or not tool_name:
        return None
    if tool_name == "lsp":
        arguments = data.get("arguments")
        if isinstance(arguments, dict) and isinstance(arguments.get("operation"), str):
            return f"lsp:{arguments['operation']}"
    return tool_name


def parse_output(output_lines: Sequence[str], *, log_transcript: bool = False) -> tuple[AgentMetrics | None, str | None]:
    execution_time: float | None = None
    llm_duration: float | None = None
    ai_credits: float | None = None
    turn_count = 0
    tool_usage: Counter[str] = Counter()
    response: str | None = None
    final_response: str | None = None

    for line_number, line in enumerate(output_lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            logger.warning("Skipping invalid JSON from Copilot CLI output at line %s: %s", line_number, error)
            continue
        if not isinstance(event, dict):
            logger.warning("Skipping non-object JSON from Copilot CLI output at line %s", line_number)
            continue

        match event.get("type"):
            case "model.call_start":
                turn_count += 1
            case "tool.execution_start":
                data = event.get("data")
                if isinstance(data, dict) and (label := _tool_label(data)):
                    tool_usage[label] += 1
                    if log_transcript:
                        logger.info("Copilot tool: %s", label)
            case "assistant.message":
                data = event.get("data")
                if not isinstance(data, dict):
                    continue
                content = data.get("content")
                if isinstance(content, str) and content:
                    response = content
                    if log_transcript and content.strip():
                        logger.info("Copilot: %s", content.strip())
                    if data.get("phase") == "final_answer":
                        final_response = content
            case "session.usage_checkpoint":
                data = event.get("data")
                if isinstance(data, dict) and (total_nano_aiu := _as_float(data.get("totalNanoAiu"))) is not None:
                    ai_credits = total_nano_aiu / NANO_AIU_PER_AI_CREDIT
            case "result":
                usage = event.get("usage")
                if isinstance(usage, dict):
                    execution_time = _milliseconds_to_seconds(usage.get("sessionDurationMs"))
                    llm_duration = _milliseconds_to_seconds(usage.get("totalApiDurationMs"))

    if execution_time is None and llm_duration is None and ai_credits is None and not turn_count:
        logger.warning("No metrics found in Copilot JSON output")
        return None, final_response or response
    return (
        AgentMetrics(
            execution_time=execution_time,
            llm_duration=llm_duration,
            ai_credits=ai_credits,
            turn_count=turn_count or None,
            tool_usage=dict(tool_usage) or None,
        ),
        final_response or response,
    )
