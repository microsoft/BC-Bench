import json
from collections import Counter
from collections.abc import Sequence

from bcbench.logger import get_logger
from bcbench.types import AgentMetrics

logger = get_logger(__name__)

# Verified against the CLI's own "AI Credits" footer: 9613375000 nano-AIU renders as "AI Credits 9.61".
NANO_AIU_PER_AI_CREDIT = 1_000_000_000


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):  # bool is an int subclass
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


def parse_output(output_lines: Sequence[str]) -> tuple[AgentMetrics | None, str | None]:
    """Parse metrics and the agent's final response from `copilot --output-format=json` (JSONL) stdout.

    Relevant events (CLI 1.0.80):
        model.call_start: one per request sent to the model, so counting them yields the turn count.
        tool.execution_start: one per tool invocation, including sub-agent and MCP tool calls.
        session.usage_checkpoint: `data.totalNanoAiu` is cumulative for the session, so the last one wins.
        result: terminal event whose `usage` sits at the event root rather than under `data`.

    Returns:
        The parsed metrics (None when the stream carried none) and the agent's final response.
    """
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
            logger.warning(f"Skipping invalid JSON from Copilot CLI output at line {line_number}: {error}")
            continue

        if not isinstance(event, dict):
            logger.warning(f"Skipping non-object JSON from Copilot CLI output at line {line_number}")
            continue

        match event.get("type"):
            case "model.call_start":
                turn_count += 1
            case "tool.execution_start":
                data = event.get("data")
                if isinstance(data, dict) and (label := _tool_label(data)):
                    tool_usage[label] += 1
            case "assistant.message":
                data = event.get("data")
                if not isinstance(data, dict):
                    continue

                content = data.get("content")
                if isinstance(content, str) and content:
                    response = content
                    if data.get("phase") == "final_answer":
                        final_response = content
            case "session.usage_checkpoint":
                data = event.get("data")
                if not isinstance(data, dict):
                    continue

                total_nano_aiu = _as_float(data.get("totalNanoAiu"))
                if total_nano_aiu is not None:
                    ai_credits = total_nano_aiu / NANO_AIU_PER_AI_CREDIT
            case "result":
                usage = event.get("usage")
                if not isinstance(usage, dict):
                    continue

                execution_time = _milliseconds_to_seconds(usage.get("sessionDurationMs"))
                llm_duration = _milliseconds_to_seconds(usage.get("totalApiDurationMs"))

    metrics = None
    if execution_time is not None or llm_duration is not None or ai_credits is not None or turn_count:
        metrics = AgentMetrics(
            execution_time=execution_time,
            llm_duration=llm_duration,
            ai_credits=ai_credits,
            turn_count=turn_count or None,
            tool_usage=dict(tool_usage) or None,
        )
    else:
        logger.warning("No metrics found in Copilot JSON output")

    return metrics, final_response or response
