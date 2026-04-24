import json
from pathlib import Path

from bcbench.operations.hooks_operations import setup_hooks
from bcbench.types import AgentType


class TestSetupHooks:
    def test_copilot_creates_hooks_json(self, tmp_path: Path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        tool_log_path = setup_hooks(repo_path, AgentType.COPILOT, output_dir)

        hooks_file = repo_path / ".github" / "hooks" / "bcbench-hooks.json"
        assert hooks_file.exists()

        hooks_config = json.loads(hooks_file.read_text(encoding="utf-8"))
        assert hooks_config["version"] == 1
        assert "preToolUse" in hooks_config["hooks"]
        assert len(hooks_config["hooks"]["preToolUse"]) == 1

        hook = hooks_config["hooks"]["preToolUse"][0]
        assert hook["type"] == "command"
        assert "powershell" in hook
        assert "BCBENCH_TOOL_LOG" in hook["env"]
        assert hook["timeoutSec"] == 5

        assert tool_log_path == output_dir / "tool_usage.jsonl"

    def test_claude_creates_settings_json(self, tmp_path: Path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        tool_log_path = setup_hooks(repo_path, AgentType.CLAUDE, output_dir)

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

        setup_hooks(repo_path, AgentType.CLAUDE, output_dir)

        settings = json.loads((claude_dir / "settings.local.json").read_text(encoding="utf-8"))
        assert settings["allowedTools"] == ["bash", "edit"]
        assert "hooks" in settings

    def test_hook_script_path_is_absolute(self, tmp_path: Path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        setup_hooks(repo_path, AgentType.COPILOT, output_dir)

        hooks_file = repo_path / ".github" / "hooks" / "bcbench-hooks.json"
        hooks_config = json.loads(hooks_file.read_text(encoding="utf-8"))
        powershell_cmd = hooks_config["hooks"]["preToolUse"][0]["powershell"]

        # The command should contain an absolute path to the script
        assert "log-tool-usage.ps1" in powershell_cmd
        assert Path(powershell_cmd.split('"')[1]).is_absolute()

    def test_tool_log_path_is_absolute_in_env(self, tmp_path: Path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        setup_hooks(repo_path, AgentType.COPILOT, output_dir)

        hooks_file = repo_path / ".github" / "hooks" / "bcbench-hooks.json"
        hooks_config = json.loads(hooks_file.read_text(encoding="utf-8"))
        log_path = hooks_config["hooks"]["preToolUse"][0]["env"]["BCBENCH_TOOL_LOG"]

        assert Path(log_path).is_absolute()
