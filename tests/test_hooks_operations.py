import json
import shlex
from pathlib import Path

from bcbench.operations.hooks_operations import setup_hooks
from bcbench.types import AgentHarness, EvaluationCategory


class TestRequiredAgentOutputFile:
    def test_data_query_requires_answer_json(self):
        assert EvaluationCategory.DATA_QUERY.required_agent_output_file == "answer.json"

    def test_other_categories_require_no_file(self):
        assert EvaluationCategory.BUG_FIX.required_agent_output_file is None
        assert EvaluationCategory.CODE_REVIEW.required_agent_output_file is None


class TestSetupHooks:
    def test_copilot_creates_hooks_json(self, tmp_path: Path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        tool_log_path = setup_hooks(repo_path, AgentHarness.COPILOT, output_dir)

        hooks_file = repo_path / ".github" / "hooks" / "bcbench-hooks.json"
        assert hooks_file.exists()

        hooks_config = json.loads(hooks_file.read_text(encoding="utf-8"))
        assert hooks_config["version"] == 1
        assert "preToolUse" in hooks_config["hooks"]
        assert len(hooks_config["hooks"]["preToolUse"]) == 1

        hook = hooks_config["hooks"]["preToolUse"][0]
        assert hook["type"] == "command"
        assert "command" in hook
        assert "BCBENCH_TOOL_LOG" in hook["env"]
        assert hook["timeoutSec"] == 5

        assert tool_log_path == output_dir / "tool_usage.jsonl"

    def test_claude_creates_settings_json(self, tmp_path: Path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        tool_log_path = setup_hooks(repo_path, AgentHarness.CLAUDE, output_dir)

        settings_file = repo_path / ".claude" / "settings.local.json"
        assert settings_file.exists()

        settings = json.loads(settings_file.read_text(encoding="utf-8"))
        assert "hooks" in settings
        assert "PreToolUse" in settings["hooks"]
        assert len(settings["hooks"]["PreToolUse"]) == 1

        hook = settings["hooks"]["PreToolUse"][0]
        assert hook["matcher"] == ""
        assert len(hook["hooks"]) == 1
        inner_hook = hook["hooks"][0]
        assert inner_hook["type"] == "command"
        assert "BCBENCH_TOOL_LOG" in inner_hook["command"]
        assert "log-tool-usage.ps1" in inner_hook["command"]

        assert tool_log_path == output_dir / "tool_usage.jsonl"

    def test_claude_preserves_existing_settings(self, tmp_path: Path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        claude_dir = repo_path / ".claude"
        claude_dir.mkdir()
        existing = {"allowedTools": ["bash", "edit"]}
        (claude_dir / "settings.local.json").write_text(json.dumps(existing), encoding="utf-8")

        setup_hooks(repo_path, AgentHarness.CLAUDE, output_dir)

        settings = json.loads((claude_dir / "settings.local.json").read_text(encoding="utf-8"))
        assert settings["allowedTools"] == ["bash", "edit"]
        assert "hooks" in settings

    def test_hook_script_path_is_absolute(self, tmp_path: Path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        setup_hooks(repo_path, AgentHarness.COPILOT, output_dir)

        hooks_file = repo_path / ".github" / "hooks" / "bcbench-hooks.json"
        hooks_config = json.loads(hooks_file.read_text(encoding="utf-8"))
        powershell_cmd = hooks_config["hooks"]["preToolUse"][0]["command"]

        # The command should contain an absolute path to the script
        assert "log-tool-usage.ps1" in powershell_cmd
        assert Path(powershell_cmd.split('"')[1]).is_absolute()

    def test_tool_log_path_is_absolute_in_env(self, tmp_path: Path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        setup_hooks(repo_path, AgentHarness.COPILOT, output_dir)

        hooks_file = repo_path / ".github" / "hooks" / "bcbench-hooks.json"
        hooks_config = json.loads(hooks_file.read_text(encoding="utf-8"))
        log_path = hooks_config["hooks"]["preToolUse"][0]["env"]["BCBENCH_TOOL_LOG"]

        assert Path(log_path).is_absolute()

    def test_claude_no_stop_hook_without_required_output(self, tmp_path: Path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        setup_hooks(repo_path, AgentHarness.CLAUDE, output_dir)

        settings = json.loads((repo_path / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
        assert "Stop" not in settings["hooks"]

    def test_claude_adds_stop_hook_for_required_output(self, tmp_path: Path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        setup_hooks(repo_path, AgentHarness.CLAUDE, output_dir, required_output_file="answer.json")

        settings = json.loads((repo_path / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
        assert len(settings["hooks"]["Stop"]) == 1
        command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert "require-answer-file.ps1" in command
        assert "BCBENCH_ANSWER_PATH=" in command
        assert "BCBENCH_STOP_COUNTER=" in command
        assert "BCBENCH_STOP_MAX=" in command
        # The forced-write target is the required file in the repo the evaluation reads.
        assert shlex.quote(str((repo_path / "answer.json").resolve())) in command

    def test_stop_hook_command_escapes_shell_metacharacters(self, tmp_path: Path):
        repo_path = tmp_path / "repo$(id)"
        repo_path.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        setup_hooks(repo_path, AgentHarness.CLAUDE, output_dir, required_output_file="answer.json")

        settings = json.loads((repo_path / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
        command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert 'BCBENCH_ANSWER_PATH="' not in command
        assert shlex.quote(str((repo_path / "answer.json").resolve())) in command
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        output_dir = tmp_path / "results$(id)`whoami`"
        output_dir.mkdir()

        setup_hooks(repo_path, AgentHarness.CLAUDE, output_dir)

        settings = json.loads((repo_path / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
        command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]

        # shlex.quote wraps the path in single quotes so $() and backticks are inert.
        assert command.startswith("BCBENCH_TOOL_LOG='")
        assert 'BCBENCH_TOOL_LOG="' not in command
        assert shlex.quote(str((output_dir / "tool_usage.jsonl").resolve())) in command
