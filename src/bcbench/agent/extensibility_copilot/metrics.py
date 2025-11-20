import re
from typing import Sequence
import json

from bcbench.logger import get_logger

logger = get_logger(__name__)


def parse_metrics(output_lines: Sequence[str]) -> dict[str, float | int] | None:
    """Parse metrics from Copilot CLI output.
    This is highly delicate and depends on the exact formatting of the CLI output.

    Expected output format at the end:
        Total usage est:       1 Premium request
        Total duration (API):  34.5s
        Total duration (wall): 3m 55.1s
        Total code changes:    2 lines added, 1 lines removed
        Usage by model:
            gpt-5                125.5k input, 3.6k output, 0 cache read, 0 cache write (Est. 1 Premium request)

    TODO: agent logs have been added to output, so parsing can be made more robust
    """
    if not output_lines:
        logger.warning("No output lines to parse metrics from")
        return None

    output_text = "".join(output_lines)
    logger.debug(f"Parsing metrics from output:\n{output_text}")

    metrics: dict[str, float | int] = {}

    try:
        duration_match = re.search(r"Total duration \(wall\):\s*(?:(\d+)m\s*)?(\d+(?:\.\d+)?)s", output_text)
        if duration_match:
            minutes = int(duration_match.group(1)) if duration_match.group(1) else 0
            seconds = float(duration_match.group(2))
            metrics["agent_execution_time"] = minutes * 60 + seconds

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

            metrics["prompt_tokens"] = parse_token_count(input_str)
            metrics["completion_tokens"] = parse_token_count(output_str)

        premium_requests_match = re.search(r"Total usage est:\s*([\d\.]+)\s*Premium request", output_text)
        if premium_requests_match:
            metrics["agent_premium_requests"] = float(premium_requests_match.group(1))

        json_output = {}
        json_match = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", output_text)
        if json_match:
            json_str = json_match.group(1)
            try:
                json_output = json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON metrics: {e}")

        metrics["json_output"] = json_output


        # Count number of occurences of '"usage": {"' in output
        number_of_steps = len(re.findall(r'"usage":\s*\{', output_text))
        metrics["number_of_steps"] = number_of_steps

        if metrics:
            logger.info(f"Parsed metrics: {metrics}")
            return metrics

        logger.warning("No metrics found in output")
        return None

    except Exception as e:
        logger.error(f"Failed to parse metrics from output: {e}")
        return None
