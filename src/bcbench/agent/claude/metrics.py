import json
from collections import Counter
from collections.abc import Sequence

from bcbench.logger import get_logger
from bcbench.types import AgentMetrics

logger = get_logger(__name__)


def parse_metrics(data: dict) -> AgentMetrics | None:
    logger.debug(f"Parsing metrics from Claude Code output: {data}")

    execution_time: float | None = None
    llm_duration: float | None = None
    turn_count: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    if "duration_ms" in data:
        execution_time = data["duration_ms"] / 1000.0

    if "duration_api_ms" in data:
        llm_duration = data["duration_api_ms"] / 1000.0

    if "num_turns" in data:
        turn_count = data["num_turns"]

    usage = data.get("usage", {})
    if usage:
        input_tokens = usage.get("input_tokens", 0)
        cache_creation = usage.get("cache_creation_input_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        prompt_tokens = input_tokens + cache_creation + cache_read
        completion_tokens = usage.get("output_tokens")

    if any(v is not None for v in [execution_time, llm_duration, turn_count, prompt_tokens, completion_tokens]):
        return AgentMetrics(
            execution_time=execution_time,
            llm_duration=llm_duration,
            turn_count=turn_count,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    logger.warning("No metrics found in Claude Code output")
    return None


def parse_stream_output(output_lines: Sequence[str]) -> tuple[AgentMetrics | None, str | None]:
    """Parse metrics + final response from `claude --output-format=stream-json --verbose` (JSONL) stdout.

    Event shapes (Claude Code):
        assistant: ``message.content`` holds ``tool_use`` blocks whose ``name`` (e.g.
            ``mcp__bcmcp__bc_data_query``) captures sub-agent and MCP tool calls the pre-tool-use hook
            never sees.
        result: terminal event carrying duration/turns/usage and the final ``result`` text.

    Returns:
        The parsed metrics (with tool usage from the stream) and the agent's final response text.
    """
    tool_usage: Counter[str] = Counter()
    final_response: str | None = None
    metrics: AgentMetrics | None = None

    for line_number, line in enumerate(output_lines, start=1):
        if not line.strip():
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            logger.warning(f"Skipping invalid JSON from Claude Code output at line {line_number}: {error}")
            continue

        if not isinstance(event, dict):
            continue

        match event.get("type"):
            case "assistant":
                message = event.get("message")
                if isinstance(message, dict):
                    for block in message.get("content", []):
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            name = block.get("name")
                            if isinstance(name, str) and name:
                                tool_usage[name] += 1
            case "result":
                metrics = parse_metrics(event)
                result_text = event.get("result")
                if isinstance(result_text, str) and result_text:
                    final_response = result_text

    if tool_usage:
        metrics = (metrics or AgentMetrics()).model_copy(update={"tool_usage": dict(tool_usage)})

    return metrics, final_response
