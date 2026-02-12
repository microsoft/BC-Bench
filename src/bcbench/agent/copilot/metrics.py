import json
import re
from collections import Counter
from pathlib import Path
from typing import Sequence

from bcbench.logger import get_logger
from bcbench.types import AgentMetrics, ExtAgentMetrics

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
        # Parse LLM duration (API time)
        llm_duration_match = re.search(r"Total duration \(API\):\s*(?:(\d+)m\s*)?(\d+(?:\.\d+)?)s", output_text)
        if llm_duration_match:
            minutes = int(llm_duration_match.group(1)) if llm_duration_match.group(1) else 0
            seconds = float(llm_duration_match.group(2))
            llm_duration = minutes * 60 + seconds

        # Parse wall clock duration
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


# Pattern to find JSON code fences with real newlines
_JSON_FENCE_REAL_NEWLINES = re.compile(r"```json\s*(\{[\s\S]*?\})\s*```")

# Pattern to find JSON code fences with literal \n (escaped newlines in JSON string values
# found in session log files where assistant content is stored as JSON strings)
_JSON_FENCE_ESCAPED_NEWLINES = re.compile(r"```json\\n(\{.*?\})\\n```")


def _unescape_json_string(s: str) -> str:
    """Unescape a JSON-encoded string value (handles \\n, \\", \\\\ etc.)."""
    try:
        return json.loads(f'"{s}"')
    except json.JSONDecodeError:
        return s


# Required keys for the Final_Output JSON schema from step7-labels-comments
_FINAL_OUTPUT_KEYS = {"labels_to_apply", "comment_to_post", "state_of_issue"}


def _normalize_final_output(raw: dict) -> dict:
    return {
        "labels_to_apply": raw.get("labels_to_apply", []),
        "comment_to_post": raw.get("comment_to_post", ""),
        "state_of_issue": raw.get("state_of_issue", ""),
    }


def _extract_last_json_from_fences(text: str) -> dict:
    """Extract the Final_Output JSON from code fences in text.

    Returns a dict with exactly {labels_to_apply, comment_to_post, state_of_issue}.
    Missing keys default to empty values.
    """
    candidates: list[str] = []

    # Match fences with real newlines
    candidates.extend(m.group(1) for m in _JSON_FENCE_REAL_NEWLINES.finditer(text))

    # Match fences with literal \n (session log format where content is inside JSON strings)
    for m in _JSON_FENCE_ESCAPED_NEWLINES.finditer(text):
        # Content is JSON-escaped — unescape via json.loads to handle \n, \", \\\\ etc.
        candidates.append(_unescape_json_string(m.group(1)))

    # Parse all candidates
    parsed: list[dict] = []
    for json_str in candidates:
        try:
            obj = json.loads(json_str)
            if isinstance(obj, dict):
                parsed.append(obj)
        except json.JSONDecodeError:
            continue

    # Only match blocks that have at least one exact Final_Output key
    matches = [p for p in parsed if _FINAL_OUTPUT_KEYS & p.keys()]
    if matches:
        return _normalize_final_output(matches[-1])

    return _normalize_final_output({})


def parse_metrics_ext(output_lines: Sequence[str], session_log_path: Path | None = None) -> ExtAgentMetrics | None:
    """Parse extended metrics from Copilot CLI output and session logs.

    This extends parse_metrics() by additionally extracting JSON output from code fences.

    Args:
        output_lines: Lines from Copilot CLI stderr output
        session_log_path: Optional path to session log file for tool usage parsing

    Returns:
        ExtAgentMetrics with all base metrics plus json_output field, or None if parsing fails
    """
    # Parse base metrics using the standard parser
    base_metrics = parse_metrics(output_lines, session_log_path)
    if base_metrics is None:
        return None

    # Extract Final_Output JSON (labels_to_apply, comment_to_post, state_of_issue)
    output_text = "".join(output_lines)
    json_output = _normalize_final_output({})

    try:
        # First, try to find JSON in stderr output (real newlines)
        json_output = _extract_last_json_from_fences(output_text)

        # If all values are empty and we have a session log, search there
        if not any(json_output.values()) and session_log_path and session_log_path.exists():
            try:
                session_content = session_log_path.read_text(encoding="utf-8")
                json_output = _extract_last_json_from_fences(session_content)
                if any(json_output.values()):
                    logger.debug(f"Found JSON output in session log: {session_log_path}")
            except Exception as e:
                logger.warning(f"Failed to read session log for JSON extraction: {e}")
    except Exception as e:
        logger.warning(f"Failed to parse JSON output: {e}")

    logger.info(f"Extracted JSON output: {json_output}")

    return ExtAgentMetrics(
        execution_time=base_metrics.execution_time,
        llm_duration=base_metrics.llm_duration,
        turn_count=base_metrics.turn_count,
        prompt_tokens=base_metrics.prompt_tokens,
        completion_tokens=base_metrics.completion_tokens,
        tool_usage=base_metrics.tool_usage,
        json_output=json.dumps(json_output),
    )
