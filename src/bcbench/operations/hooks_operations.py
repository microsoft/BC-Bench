import contextlib
import json
from pathlib import Path

from bcbench.config import get_config
from bcbench.logger import get_logger
from bcbench.types import AgentType

logger = get_logger(__name__)
_config = get_config()


def setup_hooks(repo_path: Path, agent_type: AgentType, output_dir: Path) -> Path:
    tool_log_path = output_dir / _config.file_patterns.tool_usage_log
    tool_log_path.unlink(missing_ok=True)
    ps_script = str(_config.paths.hook_script_path.resolve())
    py_script = str(_config.paths.hook_script_path_py.resolve())

    match agent_type:
        case AgentType.COPILOT:
            _setup_copilot_hooks(repo_path, ps_script, py_script, tool_log_path)
        case AgentType.CLAUDE:
            _setup_claude_hooks(repo_path, ps_script, tool_log_path)
        case _:
            raise ValueError(f"Unknown AgentType: {agent_type}")

    logger.info(f"Hooks configured for {agent_type.value}, tool log: {tool_log_path}")
    return tool_log_path


def _setup_copilot_hooks(repo_path: Path, ps_script: str, py_script: str, tool_log_path: Path) -> None:
    hooks_dir = repo_path / ".github" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Per https://docs.github.com/en/copilot/reference/hooks-reference, only the field matching
    # the runner OS is honored: `bash` on Linux/macOS and `powershell` on Windows. We use Python
    # on Linux (preinstalled, no pwsh/stdin quirks) and keep the .ps1 path on Windows where it
    # already works for bug-fix/test-gen runs on self-hosted runners.
    hooks_config = {
        "version": 1,
        "hooks": {
            "preToolUse": [
                {
                    "type": "command",
                    "bash": f'python3 "{py_script}"',
                    "powershell": f'powershell -ExecutionPolicy Bypass -File "{ps_script}"',
                    "env": {"BCBENCH_TOOL_LOG": str(tool_log_path.resolve())},
                    "timeoutSec": 5,
                }
            ]
        },
    }

    config_file = hooks_dir / _config.file_patterns.copilot_hooks_config
    config_file.write_text(json.dumps(hooks_config, indent=2), encoding="utf-8")
    logger.debug(f"Copilot hooks config written to {config_file}")


def _setup_claude_hooks(repo_path: Path, script_path: str, tool_log_path: Path) -> None:
    claude_dir = repo_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    settings_file = claude_dir / _config.file_patterns.claude_settings_local
    existing_settings: dict = {}
    if settings_file.exists():
        with contextlib.suppress(json.JSONDecodeError):
            existing_settings = json.loads(settings_file.read_text(encoding="utf-8"))

    tool_log_resolved = str(tool_log_path.resolve())
    existing_settings["hooks"] = {
        "PreToolUse": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": f'BCBENCH_TOOL_LOG="{tool_log_resolved}" powershell -ExecutionPolicy Bypass -File "{script_path}"',
                    }
                ],
            }
        ]
    }

    settings_file.write_text(json.dumps(existing_settings, indent=2), encoding="utf-8")
    logger.debug(f"Claude hooks settings written to {settings_file}")
