"""Tool usage parser for GitHub Copilot CLI log files."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from bcbench.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolUsage:
    """Tool usage statistics from Copilot CLI logs."""

    tool_counts: Counter[str] = field(default_factory=Counter)

    def __str__(self) -> str:
        """Default serialization for CLI output, sorted by usage count (descending)."""
        if not self.tool_counts:
            return "No tool usage found."

        lines = ["Tool Usage Summary:", "-" * 40]
        for tool_name, count in self.tool_counts.most_common():
            lines.append(f"  {tool_name}: {count}")
        lines.append("-" * 40)
        lines.append(f"Total tool calls: {self.total_calls}")
        return "\n".join(lines)

    @property
    def total_calls(self) -> int:
        return sum(self.tool_counts.values())

    def merge(self, other: ToolUsage) -> ToolUsage:
        """Merge another ToolUsage into this one."""
        merged = ToolUsage(tool_counts=Counter(self.tool_counts))
        merged.tool_counts.update(other.tool_counts)
        return merged


def parse_tool_usage_from_log(log_path: Path) -> ToolUsage:
    """Parse tool usage from a single Copilot CLI log file.

    The log file format is expected to be newline-delimited JSON (NDJSON/JSONL)
    where each line contains a log entry with potential tool call information.

    Args:
        log_path: Path to the Copilot CLI log file

    Returns:
        ToolUsage with counted tool calls from the log
    """
    tool_counts: Counter[str] = Counter()

    if not log_path.exists():
        logger.warning(f"Log file not found: {log_path}")
        return ToolUsage(tool_counts=tool_counts)

    try:
        content = log_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read log file {log_path}: {e}")
        return ToolUsage(tool_counts=tool_counts)

    for line_num, raw_line in enumerate(content.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue

        try:
            entry = json.loads(line)
            _extract_tool_calls(entry, tool_counts)
        except json.JSONDecodeError:
            # Skip non-JSON lines (common in log files)
            continue
        except Exception as e:
            logger.debug(f"Failed to parse line {line_num} in {log_path}: {e}")
            continue

    return ToolUsage(tool_counts=tool_counts)


def _extract_tool_calls(entry: dict, tool_counts: Counter[str]) -> None:
    """Extract tool calls from a log entry and update the counter.

    Handles various log entry formats from Copilot CLI.
    """
    # Handle direct tool call entries
    if "tool" in entry:
        tool_name = entry.get("tool")
        if tool_name:
            tool_counts[tool_name] += 1
            return

    # Handle tool_name field
    if "tool_name" in entry:
        tool_name = entry.get("tool_name")
        if tool_name:
            tool_counts[tool_name] += 1
            return

    # Handle nested tool calls in message content
    if "content" in entry and isinstance(entry["content"], dict):
        content = entry["content"]
        if "tool" in content:
            tool_counts[content["tool"]] += 1
            return
        if "tool_name" in content:
            tool_counts[content["tool_name"]] += 1
            return

    # Handle function_call format (OpenAI style)
    if "function_call" in entry:
        func = entry["function_call"]
        if isinstance(func, dict) and "name" in func:
            tool_counts[func["name"]] += 1
            return

    # Handle tool_calls array (OpenAI style)
    if "tool_calls" in entry:
        tool_calls = entry.get("tool_calls", [])
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if isinstance(tc, dict):
                    # Standard OpenAI format
                    func = tc.get("function", {})
                    if isinstance(func, dict) and "name" in func:
                        tool_counts[func["name"]] += 1
                    # Direct name format
                    elif "name" in tc:
                        tool_counts[tc["name"]] += 1

    # Handle message with role=tool or type=tool
    if entry.get("role") == "tool" or entry.get("type") == "tool":
        tool_name = entry.get("name") or entry.get("tool")
        if tool_name:
            tool_counts[tool_name] += 1


def parse_tool_usage_from_directory(directory: Path, pattern: str = "*.log") -> ToolUsage:
    """Parse tool usage from all matching log files in a directory.

    Args:
        directory: Directory to search for log files
        pattern: Glob pattern to match log files

    Returns:
        Aggregated ToolUsage from all matching files
    """
    if not directory.exists():
        logger.warning(f"Directory not found: {directory}")
        return ToolUsage()

    log_files = list(directory.rglob(pattern))
    if not log_files:
        logger.warning(f"No log files matching '{pattern}' found in {directory}")
        return ToolUsage()

    logger.info(f"Found {len(log_files)} log file(s) to analyze")

    aggregated = ToolUsage()
    for log_file in log_files:
        logger.debug(f"Parsing: {log_file}")
        usage = parse_tool_usage_from_log(log_file)
        aggregated = aggregated.merge(usage)
        # TODO: Consider tracking per-file statistics for more detailed analysis

    return aggregated
