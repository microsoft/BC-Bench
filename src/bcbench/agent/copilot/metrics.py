import re
from typing import Sequence

from bcbench.logger import get_logger
from bcbench.types import AgentMetrics

logger = get_logger(__name__)


def parse_metrics(output_lines: Sequence[str]) -> AgentMetrics | None:
    """Parse metrics from Copilot CLI output.
    This is highly delicate and depends on the exact formatting of the CLI output.

    Expected output format at the end:
        Total usage est:       1 Premium request
        Total duration (API):  34.5s
        Total duration (wall): 3m 55.1s
        Total code changes:    2 lines added, 1 lines removed
        Usage by model:
            gpt-5                125.5k input, 3.6k output, 0 cache read, 0 cache write (Est. 1 Premium request)
    """
    if not output_lines:
        logger.warning("No output lines to parse metrics from")
        return None

    output_text = "".join(output_lines)
    logger.debug(f"Parsing metrics from output:\n{output_text}")

    execution_time: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    try:
        duration_match = re.search(r"Total duration \(wall\):\s*(?:(\d+)m\s*)?(\d+(?:\.\d+)?)s", output_text)
        if duration_match:
            minutes = int(duration_match.group(1)) if duration_match.group(1) else 0
            seconds = float(duration_match.group(2))
            execution_time = minutes * 60 + seconds

        usage_match = re.search(r"(\d+(?:\.\d+)?[km]?)\s+input,\s*(\d+(?:\.\d+)?[km]?)\s+output", output_text)
        if usage_match:
            input_str = usage_match.group(1)
            output_str = usage_match.group(2)

            def parse_token_count(s: str) -> int:
                if s.endswith("m"):
                    return int(float(s[:-1]) * 1000000)
                if s.endswith("k"):
                    return int(float(s[:-1]) * 1000)
                return int(float(s))

            prompt_tokens = parse_token_count(input_str)
            completion_tokens = parse_token_count(output_str)

        if execution_time is not None or prompt_tokens is not None or completion_tokens is not None:
            return AgentMetrics(execution_time=execution_time, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)

        logger.warning("No metrics found in output")
        return None

    except Exception as e:
        logger.error(f"Failed to parse metrics from output: {e}")
        return None
