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
from pathlib import Path

from bcbench.types import ToolUsage

__all__ = ["ToolUsage", "parse_tool_usage_from_log"]

# Regex to find tool call function names in the log content
# Matches tool calls (with "arguments") but NOT tool definitions (with "description")
# Pattern: "function": {"name": "tool_name", "arguments": ...}
TOOL_CALL_PATTERN = re.compile(
    r'"function"\s*:\s*\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"',
    re.MULTILINE,
)


def parse_tool_usage_from_log(log_path: Path) -> ToolUsage:
    """Parse tool usage from a single Copilot CLI log file.

    The log file format is timestamped text with embedded JSON responses.
    Tool calls appear in response JSON under choices[].message.tool_calls[].

    Args:
        log_path: Path to the Copilot CLI log file

    Returns:
        ToolUsage with counted tool calls from the log
    """
    tool_counts: dict[str, float] = {}

    content = log_path.read_text(encoding="utf-8")

    # Use regex to find all tool call function names directly
    # This is more reliable than trying to parse multi-line JSON from logs
    matches = TOOL_CALL_PATTERN.findall(content)
    for tool_name in matches:
        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

    return ToolUsage(tool_counts=tool_counts)
