import re
from collections.abc import Sequence
from pathlib import Path

from bcbench.logger import get_logger
from bcbench.types import AgentMetrics

logger = get_logger(__name__)

# Regex to count LLM requests (turns) in the log
# Each "--- Start of group: Sending request to the AI model ---" indicates a new LLM call
TURN_COUNT_PATTERN = re.compile(r"--- Start of group: Sending request to the AI model ---")


def _parse_token_count(s: str) -> int:
    if s.endswith("m"):
        return int(float(s[:-1]) * 1000000)
    if s.endswith("k"):
        return int(float(s[:-1]) * 1000)
    return int(float(s))


def parse_turn_count_from_log(log_path: Path) -> int:
    content = log_path.read_text(encoding="utf-8")
    return len(TURN_COUNT_PATTERN.findall(content))


def parse_metrics(output_lines: Sequence[str], session_log_path: Path | None = None) -> AgentMetrics | None:
    """Parse metrics from Copilot CLI output and session logs.

    This is highly delicate and depends on the exact formatting of the CLI output.

    Args:
        output_lines: Lines from Copilot CLI stderr output
        session_log_path: Optional path to session log file for tool usage parsing

    Expected output format (v1.0.81):
        Changes    +30 -0
        AI Credits 281 (21m 6s)
        Tokens     ↑ 17.7m (16.5m cached, 1.1m written) • ↓ 171.2k (37.0k reasoning)

    Previous output format:
        Changes    +67 -0
        Requests   15 Premium (6m 47s)
        Tokens     ↑ 1.6m (1.6m cached) • ↓ 20.7k (3.2k reasoning)

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
    premium_requests: float | None = None
    ai_credits: float | None = None
    turn_count: int | None = None

    # Parse turn count from session log if provided
    if session_log_path:
        try:
            turn_count = parse_turn_count_from_log(session_log_path) or None
        except Exception as e:  # noqa: BLE001 - metrics are best-effort; never fail a run over them
            logger.warning(f"Failed to parse turn count from {session_log_path}: {e}")
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

        # Current formats include the session time after either cost unit.
        if execution_time is None:
            cost_match = re.search(r"(?:Requests\s+[\d.]+\s+Premium|AI Credits\s+[\d.]+)\s+\((?:(\d+)m\s*)?(\d+(?:\.\d+)?)s\)", output_text)
            if cost_match:
                minutes = int(cost_match.group(1)) if cost_match.group(1) else 0
                seconds = float(cost_match.group(2))
                execution_time = minutes * 60 + seconds

        # Token usage — legacy format: "1.3m in, 11.6k out"
        usage_match = re.search(r"(\d+(?:\.\d+)?[km]?)\s+in,\s*(\d+(?:\.\d+)?[km]?)\s+out", output_text)
        if usage_match:
            prompt_tokens = _parse_token_count(usage_match.group(1))
            completion_tokens = _parse_token_count(usage_match.group(2))

        # New format: "Tokens    ↑ 1.6m (1.6m cached) • ↓ 20.7k (3.2k reasoning)"
        # Anchor on the ↑/↓ arrows so parenthesized annotations between the numbers don't break parsing.
        if prompt_tokens is None:
            tokens_match = re.search(r"Tokens\s+.*?↑\s*(\d+(?:\.\d+)?[km]?).*?↓\s*(\d+(?:\.\d+)?[km]?)", output_text)
            if tokens_match:
                prompt_tokens = _parse_token_count(tokens_match.group(1))
                completion_tokens = _parse_token_count(tokens_match.group(2))

        premium_match = re.search(
            r"(?:Total usage est:\s*(\d+(?:\.\d+)?)\s+Premium requests?|Requests\s+(\d+(?:\.\d+)?)\s+Premium)",
            output_text,
        )
        if premium_match:
            premium_requests = float(premium_match.group(1) or premium_match.group(2))

        ai_credits_match = re.search(r"AI Credits\s+(\d+(?:\.\d+)?)", output_text)
        if ai_credits_match:
            ai_credits = float(ai_credits_match.group(1))

        if (
            execution_time is not None
            or llm_duration is not None
            or prompt_tokens is not None
            or completion_tokens is not None
            or premium_requests is not None
            or ai_credits is not None
            or turn_count is not None
        ):
            return AgentMetrics(
                execution_time=execution_time,
                llm_duration=llm_duration,
                turn_count=turn_count,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                premium_requests=premium_requests,
                ai_credits=ai_credits,
            )

    except Exception:
        logger.exception("Failed to parse metrics from output")
        return None
    else:
        logger.warning("No metrics found in output")
        return None
