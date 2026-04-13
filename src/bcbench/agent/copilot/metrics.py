import re
from collections import Counter
from pathlib import Path
from typing import Sequence

from bcbench.logger import get_logger
from bcbench.types import AgentMetrics

logger = get_logger(__name__)

# Regex to find tool call function names in the log content
# Matches tool calls (with "arguments") but NOT tool definitions (with "description")
# Pattern: "function": {"name": "tool_name", "arguments": ...}
TOOL_CALL_PATTERN = re.compile(
    r'"function"\s*:\s*\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"',
    re.MULTILINE,
)

# Regex to count LLM requests (turns) in the log
# Each "--- Start of group: Sending request to the AI model ---" indicates a new LLM call
TURN_COUNT_PATTERN = re.compile(r"--- Start of group: Sending request to the AI model ---")


def _parse_token_count(s: str) -> int:
    if s.endswith("m"):
        return int(float(s[:-1]) * 1000000)
    if s.endswith("k"):
        return int(float(s[:-1]) * 1000)
    return int(float(s))


def parse_session_log(log_path: Path) -> tuple[dict[str, int], int]:
    """Parse tool usage and step count from a single Copilot CLI log file.

    The log file format is timestamped text with embedded JSON responses.
    Tool calls appear in response JSON under choices[].message.tool_calls[].
    Step count is determined by counting LLM requests.

    Args:
        log_path: Path to the Copilot CLI log file

    Returns:
        Tuple of (tool_usage dict mapping tool names to call counts, turn_count)
    """
    content = log_path.read_text(encoding="utf-8")
    tool_usage = dict(Counter(TOOL_CALL_PATTERN.findall(content)))
    turn_count = len(TURN_COUNT_PATTERN.findall(content))
    return tool_usage, turn_count


def parse_metrics(output_lines: Sequence[str], session_log_path: Path | None = None) -> AgentMetrics | None:
    """Parse metrics from Copilot CLI output and session logs.

    This is highly delicate and depends on the exact formatting of the CLI output.

    Args:
        output_lines: Lines from Copilot CLI stderr output
        session_log_path: Optional path to session log file for tool usage parsing

    Expected output format (new, v1.0.2+):
        Changes   +17 -0
        Requests  0.33 Premium (1m 45s)
        Tokens    ↑ 317.5k • ↓ 4.3k • 255.0k (cached)

    Legacy output format:
        Total usage est:        0.33 Premium requests
        API time spent:         2m 10.145s
        Total session time:     2m 41.651s
        Total code changes:     +42 -1
        Breakdown by AI model:
         claude-haiku-4.5        1.3m in, 11.6k out, 1.2m cached (Est. 0.33 Premium requests)
    """
    if not output_lines:
        logger.warning("No output lines to parse metrics from")
        return None

    output_text = "".join(output_lines)
    logger.debug(f"Parsing metrics from output:\n{output_text}")

    execution_time: float | None = None
    llm_duration: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tool_usage: dict[str, int] | None = None
    turn_count: int | None = None

    # Parse tool usage and turn count from session log if provided
    if session_log_path:
        try:
            tool_usage, turn_count = parse_session_log(session_log_path)
            if not tool_usage:
                tool_usage = None  # Convert empty dict to None
            if turn_count == 0:
                turn_count = None  # Convert zero to None
        except Exception as e:
            logger.warning(f"Failed to parse tool usage from {session_log_path}: {e}")
            tool_usage = None
            turn_count = None

    try:
        # Parse LLM duration (API time) — legacy format
        llm_duration_match = re.search(r"API time spent:\s*(?:(\d+)m\s*)?(\d+(?:\.\d+)?)s", output_text)
        if llm_duration_match:
            minutes = int(llm_duration_match.group(1)) if llm_duration_match.group(1) else 0
            seconds = float(llm_duration_match.group(2))
            llm_duration = minutes * 60 + seconds

        # Parse wall clock duration — legacy format
        duration_match = re.search(r"Total session time:\s*(?:(\d+)m\s*)?(\d+(?:\.\d+)?)s", output_text)
        if duration_match:
            minutes = int(duration_match.group(1)) if duration_match.group(1) else 0
            seconds = float(duration_match.group(2))
            execution_time = minutes * 60 + seconds

        # New format: "Requests  0.33 Premium (1m 45s)" — extract session time from parenthesized duration
        if execution_time is None:
            requests_match = re.search(r"Requests\s+[\d.]+\s+Premium\s+\((?:(\d+)m\s*)?(\d+(?:\.\d+)?)s\)", output_text)
            if requests_match:
                minutes = int(requests_match.group(1)) if requests_match.group(1) else 0
                seconds = float(requests_match.group(2))
                execution_time = minutes * 60 + seconds

        # Token usage — legacy format: "1.3m in, 11.6k out"
        usage_match = re.search(r"(\d+(?:\.\d+)?[km]?)\s+in,\s*(\d+(?:\.\d+)?[km]?)\s+out", output_text)
        if usage_match:
            prompt_tokens = _parse_token_count(usage_match.group(1))
            completion_tokens = _parse_token_count(usage_match.group(2))

        # New format: "Tokens    ↑ 317.5k • ↓ 4.3k • 255.0k (cached)"
        if prompt_tokens is None:
            tokens_match = re.search(r"Tokens\s+[^\d]*(\d+(?:\.\d+)?[km]?)\s*[•·]\s*[^\d]*(\d+(?:\.\d+)?[km]?)", output_text)
            if tokens_match:
                prompt_tokens = _parse_token_count(tokens_match.group(1))
                completion_tokens = _parse_token_count(tokens_match.group(2))

        if execution_time is not None or llm_duration is not None or prompt_tokens is not None or completion_tokens is not None or tool_usage is not None or turn_count is not None:
            return AgentMetrics(
                execution_time=execution_time,
                llm_duration=llm_duration,
                turn_count=turn_count,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                tool_usage=tool_usage,
            )

        logger.warning("No metrics found in output")
        return None

    except Exception as e:
        logger.error(f"Failed to parse metrics from output: {e}")
        return None
