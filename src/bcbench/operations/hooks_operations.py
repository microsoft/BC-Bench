import contextlib
import json
import shlex
from dataclasses import dataclass
from pathlib import Path

from bcbench.config import get_config
from bcbench.logger import get_logger
from bcbench.types import AgentHarness

logger = get_logger(__name__)
_config = get_config()


def setup_hooks(repo_path: Path, harness: AgentHarness, output_dir: Path, required_output_file: str | None = None) -> Path:
    tool_log_path = output_dir / _config.file_patterns.tool_usage_log
    tool_log_path.unlink(missing_ok=True)
    script_path = str(_config.paths.hook_script_path.resolve())

    require_answer = _RequireAnswerHook(repo_path, output_dir, required_output_file) if required_output_file else None

    match harness:
        case AgentHarness.COPILOT:
            _setup_copilot_hooks(repo_path, script_path, tool_log_path)
        case AgentHarness.CLAUDE:
            _setup_claude_hooks(repo_path, script_path, tool_log_path, require_answer)
        case _:
            raise ValueError(f"{harness.value} does not support hooks")

    logger.info(f"Hooks configured for {harness.value}, tool log: {tool_log_path}")
    return tool_log_path


@dataclass(frozen=True)
class _RequireAnswerHook:
    """The Stop-hook environment for forcing the agent to write its required output file."""

    repo_path: Path
    output_dir: Path
    output_file: str

    @property
    def answer_path(self) -> Path:
        return (self.repo_path / self.output_file).resolve()

    @property
    def counter_path(self) -> Path:
        return (self.output_dir / "answer_hook_retries.txt").resolve()

    def env(self) -> dict[str, str]:
        self.counter_path.unlink(missing_ok=True)
        return {
            "BCBENCH_ANSWER_PATH": str(self.answer_path),
            "BCBENCH_STOP_COUNTER": str(self.counter_path),
            "BCBENCH_STOP_MAX": "3",
        }


def _setup_copilot_hooks(repo_path: Path, script_path: str, tool_log_path: Path) -> None:
    hooks_dir = repo_path / ".github" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    hooks_config = {
        "version": 1,
        "hooks": {
            "preToolUse": [
                {
                    "type": "command",
                    "command": f'pwsh -ExecutionPolicy Bypass -File "{script_path}"',
                    "env": {"BCBENCH_TOOL_LOG": str(tool_log_path.resolve())},
                    "timeoutSec": 5,
                }
            ]
        },
    }

    config_file = hooks_dir / _config.file_patterns.copilot_hooks_config
    config_file.write_text(json.dumps(hooks_config, indent=2), encoding="utf-8")
    logger.debug(f"Copilot hooks config written to {config_file}")


def _setup_claude_hooks(repo_path: Path, script_path: str, tool_log_path: Path, require_answer: "_RequireAnswerHook | None") -> None:
    claude_dir = repo_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    settings_file = claude_dir / _config.file_patterns.claude_settings_local
    existing_settings: dict = {}
    if settings_file.exists():
        with contextlib.suppress(json.JSONDecodeError):
            existing_settings = json.loads(settings_file.read_text(encoding="utf-8"))

    tool_log_quoted = shlex.quote(str(tool_log_path.resolve()))
    script_path_quoted = shlex.quote(script_path)
    hooks: dict = {
        "PreToolUse": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"BCBENCH_TOOL_LOG={tool_log_quoted} pwsh -ExecutionPolicy Bypass -File {script_path_quoted}",
                    }
                ],
            }
        ]
    }

    if require_answer is not None:
        stop_script_quoted = shlex.quote(str(_config.paths.require_answer_hook_script_path.resolve()))
        env_prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in require_answer.env().items())
        hooks["Stop"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f"{env_prefix} pwsh -ExecutionPolicy Bypass -File {stop_script_quoted}",
                    }
                ]
            }
        ]

    existing_settings["hooks"] = hooks
    settings_file.write_text(json.dumps(existing_settings, indent=2), encoding="utf-8")
    logger.debug(f"Claude hooks settings written to {settings_file}")
