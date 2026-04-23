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
