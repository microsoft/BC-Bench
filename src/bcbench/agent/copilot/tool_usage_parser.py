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

This module re-exports the parsing function from metrics.py for backward compatibility.
"""

from __future__ import annotations

from pathlib import Path

from bcbench.agent.copilot.metrics import _parse_tool_usage_from_log

__all__ = ["parse_tool_usage_from_log"]


def parse_tool_usage_from_log(log_path: Path) -> dict[str, int]:
    """Parse tool usage from a single Copilot CLI log file.

    The log file format is timestamped text with embedded JSON responses.
    Tool calls appear in response JSON under choices[].message.tool_calls[].

    Args:
        log_path: Path to the Copilot CLI log file

    Returns:
        Dict mapping tool names to call counts from the log
    """
    return _parse_tool_usage_from_log(log_path)
