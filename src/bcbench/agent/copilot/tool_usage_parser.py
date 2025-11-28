"""Tool usage parser for GitHub Copilot CLI log files.

Parses timestamped log files containing embedded JSON responses from the Copilot API.
Extracts tool call information from the nested response structure.

Log format example:
    2025-11-28T14:26:41.178Z [DEBUG] data:
    {
      "choices": [{
        "message": {
          "tool_calls": [{"function": {"name": "view", ...}}]
        }
      }]
    }
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from bcbench.logger import get_logger

logger = get_logger(__name__)

# Regex to find tool call function names in the log content
# Matches tool calls (with "arguments") but NOT tool definitions (with "description")
# Pattern: "function": {"name": "tool_name", "arguments": ...}
TOOL_CALL_PATTERN = re.compile(
    r'"function"\s*:\s*\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"',
    re.MULTILINE,
)


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

    The log file format is timestamped text with embedded JSON responses.
    Tool calls appear in response JSON under choices[].message.tool_calls[].

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

    # Strategy 1: Use regex to find all tool call function names directly
    # This is more reliable than trying to parse multi-line JSON from logs
    matches = TOOL_CALL_PATTERN.findall(content)
    for tool_name in matches:
        tool_counts[tool_name] += 1

    # Strategy 2: Try to extract and parse JSON blocks for more structured data
    # TODO: Consider implementing JSON block extraction for richer analysis
    # (e.g., extracting arguments, timestamps, success/failure status)

    return ToolUsage(tool_counts=tool_counts)
