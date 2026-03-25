import re
from collections import Counter
from pathlib import Path

from bcbench.logger import get_logger
from bcbench.types import AgentMetrics

logger = get_logger(__name__)

TOOL_USE_PATTERN = re.compile(r"executePreToolHooks called for tool: (.+)")


def parse_debug_log(log_path: Path) -> dict[str, int]:
    content = log_path.read_text(encoding="utf-8")
    return dict(Counter(TOOL_USE_PATTERN.findall(content)))


def parse_metrics(data: dict, debug_log_path: Path | None = None) -> AgentMetrics | None:
    """Parse metrics from Claude Code result object.

    The Claude Code CLI outputs JSON when run with --output-format json.
    Expected format:
    {
        "type": "result",
        "subtype": "success",
        "is_error": false,
        "duration_ms": 2814,
        "duration_api_ms": 4819,
        "num_turns": 1,
        "result": "...",
        "session_id": "uuid",
        "total_cost_usd": 0.024,
        "usage": {
            "input_tokens": 2,
            "cache_creation_input_tokens": 4974,
            "cache_read_input_tokens": 12673,
            "output_tokens": 5,
            ...
        },
        ...
    }
    """
    logger.debug(f"Parsing metrics from Claude Code output: {data}")

    # Extract metrics from JSON
    execution_time: float | None = None
    llm_duration: float | None = None
    turn_count: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tool_usage: dict[str, int] | None = None

    # Wall clock duration (ms -> seconds)
    if "duration_ms" in data:
        execution_time = data["duration_ms"] / 1000.0

    # API duration (ms -> seconds)
    if "duration_api_ms" in data:
        llm_duration = data["duration_api_ms"] / 1000.0

    # Turn count
    if "num_turns" in data:
        turn_count = data["num_turns"]

    # Token usage from the usage object
    usage = data.get("usage", {})
    if usage:
        # Input tokens = direct input + cache creation + cache read
        input_tokens = usage.get("input_tokens", 0)
        cache_creation = usage.get("cache_creation_input_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        prompt_tokens = input_tokens + cache_creation + cache_read

        completion_tokens = usage.get("output_tokens")

    if debug_log_path and debug_log_path.exists():
        try:
            tool_usage = parse_debug_log(debug_log_path) or None
        except Exception as e:
            logger.warning(f"Failed to parse tool usage from {debug_log_path}: {e}")

    if any(v is not None for v in [execution_time, llm_duration, turn_count, prompt_tokens, completion_tokens]):
        return AgentMetrics(
            execution_time=execution_time,
            llm_duration=llm_duration,
            turn_count=turn_count,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            tool_usage=tool_usage,
        )

    logger.warning("No metrics found in Claude Code output")
    return None
