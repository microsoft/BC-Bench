from pathlib import Path

from bcbench.agent.copilot.tool_usage_parser import ToolUsage, parse_tool_usage_from_log


class TestToolUsage:
    def test_serialization_to_dict(self):
        usage = ToolUsage(tool_counts={"bash": 5, "view": 3})
        data = usage.model_dump()

        assert data["tool_counts"] == {"bash": 5, "view": 3}

    def test_deserialization_from_dict(self):
        data = {"tool_counts": {"bash": 5, "view": 3}}
        usage = ToolUsage.model_validate(data)

        assert usage.tool_counts["bash"] == 5
        assert usage.tool_counts["view"] == 3


class TestParseToolUsageFromLog:
    def test_parses_tool_calls_from_copilot_log_format(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        # Actual Copilot CLI log format with tool calls
        log_content = """
2025-01-01T00:00:00.000Z [DEBUG] data:
{
  "tool_calls": [
    {"function": {"name": "bash", "arguments": "{}"}},
    {"function": {"name": "bash", "arguments": "{}"}}
  ]
}
2025-01-01T00:00:01.000Z [DEBUG] data:
{
  "tool_calls": [
    {"function": {"name": "view", "arguments": "{\\"path\\": \\"/tmp\\"}"}}
  ]
}
"""
        log_file.write_text(log_content)

        usage = parse_tool_usage_from_log(log_file)

        assert usage.tool_counts["bash"] == 2
        assert usage.tool_counts["view"] == 1

    def test_ignores_tool_definitions(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        # Tool definitions have "description" not "arguments"
        log_content = """
2025-01-01T00:00:00.000Z [DEBUG] Tools:
[
  {"type": "function", "function": {"name": "view", "description": "View files", "parameters": {}}}
]
"""
        log_file.write_text(log_content)

        usage = parse_tool_usage_from_log(log_file)

        assert usage.tool_counts.get("view", 0) == 0

    def test_parses_mixed_tool_calls_and_definitions(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_content = """
2025-01-01T00:00:00.000Z [DEBUG] Tools:
[
  {"type": "function", "function": {"name": "view", "description": "View files"}}
]
2025-01-01T00:00:01.000Z [DEBUG] data:
{
  "tool_calls": [
    {"function": {"name": "view", "arguments": "{\\"path\\": \\"/tmp\\"}"}}
  ]
}
"""
        log_file.write_text(log_content)

        usage = parse_tool_usage_from_log(log_file)

        # Should only count the actual tool call, not the definition
        assert usage.tool_counts["view"] == 1

    def test_skips_non_json_lines(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_content = """Not JSON line
2025-01-01T00:00:00.000Z [LOG] Some log message
{"function": {"name": "bash", "arguments": "{}"}}
Another non-JSON line
"""
        log_file.write_text(log_content)

        usage = parse_tool_usage_from_log(log_file)

        assert usage.tool_counts["bash"] == 1

    def test_returns_empty_for_nonexistent_file(self, tmp_path: Path):
        log_file = tmp_path / "empty.log"
        log_file.write_text("")

        usage = parse_tool_usage_from_log(log_file)

        assert usage.tool_counts == {}

    def test_parses_mcp_tool_names(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_content = """
{"function": {"name": "bc-code-intelligence-find_bc_knowledge", "arguments": "{\\"query\\": \\"test\\"}"}}
{"function": {"name": "bc-code-intelligence-ask_bc_expert", "arguments": "{}"}}
"""
        log_file.write_text(log_content)

        usage = parse_tool_usage_from_log(log_file)

        assert usage.tool_counts["bc-code-intelligence-find_bc_knowledge"] == 1
        assert usage.tool_counts["bc-code-intelligence-ask_bc_expert"] == 1
