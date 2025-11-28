from pathlib import Path

from bcbench.agent.copilot.tool_usage_parser import (
    ToolUsage,
    parse_tool_usage_from_directory,
    parse_tool_usage_from_log,
)


class TestToolUsage:
    def test_str_empty_tool_counts_returns_no_usage_message(self):
        usage = ToolUsage()
        assert str(usage) == "No tool usage found."

    def test_str_formats_tool_counts_sorted_by_usage(self):
        from collections import Counter

        usage = ToolUsage(tool_counts=Counter({"tool_a": 5, "tool_b": 10, "tool_c": 3}))
        result = str(usage)

        assert "tool_b: 10" in result
        assert "tool_a: 5" in result
        assert "tool_c: 3" in result
        # Verify descending order
        assert result.index("tool_b") < result.index("tool_a") < result.index("tool_c")

    def test_total_calls_returns_sum_of_all_counts(self):
        from collections import Counter

        usage = ToolUsage(tool_counts=Counter({"tool_a": 5, "tool_b": 10}))
        assert usage.total_calls == 15

    def test_merge_combines_tool_counts(self):
        from collections import Counter

        usage1 = ToolUsage(tool_counts=Counter({"tool_a": 5, "tool_b": 3}))
        usage2 = ToolUsage(tool_counts=Counter({"tool_b": 2, "tool_c": 7}))

        merged = usage1.merge(usage2)

        assert merged.tool_counts["tool_a"] == 5
        assert merged.tool_counts["tool_b"] == 5
        assert merged.tool_counts["tool_c"] == 7


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

        assert usage.tool_counts["view"] == 0
        assert usage.total_calls == 0

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
        assert usage.total_calls == 1

    def test_returns_empty_for_nonexistent_file(self, tmp_path: Path):
        usage = parse_tool_usage_from_log(tmp_path / "nonexistent.log")

        assert usage.total_calls == 0

    def test_handles_empty_file(self, tmp_path: Path):
        log_file = tmp_path / "empty.log"
        log_file.write_text("")

        usage = parse_tool_usage_from_log(log_file)

        assert usage.total_calls == 0

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


class TestParseToolUsageFromDirectory:
    def test_aggregates_from_multiple_files(self, tmp_path: Path):
        (tmp_path / "log1.log").write_text('{"function": {"name": "bash", "arguments": "{}"}}\n')
        (tmp_path / "log2.log").write_text('{"function": {"name": "bash", "arguments": "{}"}}\n{"function": {"name": "view", "arguments": "{}"}}\n')

        usage = parse_tool_usage_from_directory(tmp_path, "*.log")

        assert usage.tool_counts["bash"] == 2
        assert usage.tool_counts["view"] == 1

    def test_returns_empty_for_nonexistent_directory(self, tmp_path: Path):
        usage = parse_tool_usage_from_directory(tmp_path / "nonexistent", "*.log")

        assert usage.total_calls == 0

    def test_returns_empty_when_no_files_match_pattern(self, tmp_path: Path):
        (tmp_path / "test.txt").write_text("content")

        usage = parse_tool_usage_from_directory(tmp_path, "*.log")

        assert usage.total_calls == 0

    def test_searches_recursively(self, tmp_path: Path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.log").write_text('{"function": {"name": "deep_tool", "arguments": "{}"}}\n')

        usage = parse_tool_usage_from_directory(tmp_path, "*.log")

        assert usage.tool_counts["deep_tool"] == 1
