import json
from pathlib import Path

from bcbench.agent.shared.hooks_parser import parse_tool_usage_from_hooks


class TestParseToolUsageFromHooks:
    def test_counts_tool_calls(self, tmp_path: Path):
        log_file = tmp_path / "tool_usage.jsonl"
        log_file.write_text(
            "\n".join(
                json.dumps(e)
                for e in [
                    {"tool_name": "bash", "timestamp": 1000},
                    {"tool_name": "view", "timestamp": 2000},
                    {"tool_name": "bash", "timestamp": 3000},
                    {"tool_name": "edit", "timestamp": 4000},
                ]
            ),
            encoding="utf-8",
        )

        result = parse_tool_usage_from_hooks(log_file)

        assert result == {"bash": 2, "view": 1, "edit": 1}

    def test_returns_none_for_missing_file(self, tmp_path: Path):
        result = parse_tool_usage_from_hooks(tmp_path / "nonexistent.jsonl")

        assert result is None

    def test_returns_none_for_empty_file(self, tmp_path: Path):
        log_file = tmp_path / "tool_usage.jsonl"
        log_file.write_text("", encoding="utf-8")

        result = parse_tool_usage_from_hooks(log_file)

        assert result is None

    def test_skips_malformed_lines(self, tmp_path: Path):
        log_file = tmp_path / "tool_usage.jsonl"
        log_file.write_text(
            "not json\n" + json.dumps({"tool_name": "bash", "timestamp": 1000}) + "\n\n",
            encoding="utf-8",
        )

        result = parse_tool_usage_from_hooks(log_file)

        assert result == {"bash": 1}

    def test_skips_entries_without_tool_name(self, tmp_path: Path):
        log_file = tmp_path / "tool_usage.jsonl"
        log_file.write_text(
            json.dumps({"timestamp": 1000}) + "\n" + json.dumps({"tool_name": "view", "timestamp": 2000}) + "\n",
            encoding="utf-8",
        )

        result = parse_tool_usage_from_hooks(log_file)

        assert result == {"view": 1}

    def test_handles_mcp_tool_names(self, tmp_path: Path):
        log_file = tmp_path / "tool_usage.jsonl"
        log_file.write_text(
            "\n".join(
                json.dumps(e)
                for e in [
                    {"tool_name": "bc-code-intelligence-find_bc_knowledge", "timestamp": 1000},
                    {"tool_name": "bash", "timestamp": 2000},
                    {"tool_name": "bc-code-intelligence-find_bc_knowledge", "timestamp": 3000},
                ]
            ),
            encoding="utf-8",
        )

        result = parse_tool_usage_from_hooks(log_file)

        assert result == {"bc-code-intelligence-find_bc_knowledge": 2, "bash": 1}

    def test_returns_none_for_only_blank_lines(self, tmp_path: Path):
        log_file = tmp_path / "tool_usage.jsonl"
        log_file.write_text("\n\n\n", encoding="utf-8")

        result = parse_tool_usage_from_hooks(log_file)

        assert result is None
