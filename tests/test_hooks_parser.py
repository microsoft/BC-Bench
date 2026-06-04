import json
from pathlib import Path

from bcbench.agent.shared.hooks_parser import parse_skill_read_diagnostics_from_hooks, parse_tool_usage_from_hooks
from bcbench.types import AgentType


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


class TestParseSkillReadDiagnosticsFromHooks:
    def test_returns_none_for_missing_file(self, tmp_path: Path):
        result = parse_skill_read_diagnostics_from_hooks(tmp_path / "missing.jsonl", tmp_path / "repo", AgentType.COPILOT)

        assert result is None

    def test_detects_skill_and_instruction_reads(self, tmp_path: Path):
        repo_path = tmp_path / "repo"
        hooks_file = tmp_path / "tool_usage.jsonl"

        skill_path = repo_path / ".github" / "skills" / "al-code-review" / "SKILL.md"
        security_path = repo_path / ".github" / "instructions" / "security.md"

        hooks_file.write_text(
            "\n".join(
                json.dumps(e)
                for e in [
                    {"tool_name": "Read", "tool_path": str(skill_path), "timestamp": 1000},
                    {"tool_name": "Read", "tool_path": str(security_path), "timestamp": 1100},
                ]
            ),
            encoding="utf-8",
        )

        result = parse_skill_read_diagnostics_from_hooks(hooks_file, repo_path, AgentType.COPILOT)

        assert result is not None
        assert result["skill_file_read"] is True
        assert result["instruction_security_read"] is True
        assert result["any_domain_instruction_read"] is True
        assert result["all_domain_instructions_read"] is False

    def test_case_insensitive_windows_paths(self, tmp_path: Path):
        repo_path = tmp_path / "repo"
        hooks_file = tmp_path / "tool_usage.jsonl"

        skill_path = repo_path / ".github" / "skills" / "al-code-review" / "SKILL.md"

        hooks_file.write_text(
            json.dumps({"tool_name": "read_file", "tool_path": str(skill_path).upper(), "timestamp": 1000}),
            encoding="utf-8",
        )

        result = parse_skill_read_diagnostics_from_hooks(hooks_file, repo_path, AgentType.COPILOT)

        assert result is not None
        assert result["skill_file_read"] is True
