"""Centralized configuration and constant management for BC-Bench."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import AliasPath, BaseModel, ConfigDict, Field

from bcbench.cli_options import CopilotModelName

__all__ = ["Config", "get_config"]


def _get_git_root() -> Path:
    """Get the git root directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).parent,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        # Fallback to file-based resolution if not in a git repo
        return Path(__file__).parent.parent.parent


@dataclass(frozen=True)
class PathConfig:
    """File and directory paths."""

    bc_bench_root: Path
    dataset_dir: Path
    problem_statement_dir: Path
    testbed_path: Path
    evaluation_results_path: Path
    leaderboard_dir: Path
    agent_share_dir: Path
    redteam_scorecard: Path
    plugin_root: Path

    @classmethod
    def from_root(cls, root: Path) -> PathConfig:
        """Create path configuration from repository root."""
        agent_share_dir = root / "src" / "bcbench" / "agent" / "shared"
        evaluation_results_path = root / "evaluation_results"
        return cls(
            bc_bench_root=root,
            dataset_dir=root / "dataset",
            problem_statement_dir=root / "dataset" / "problemstatement",
            testbed_path=root.parent / "NAV",
            evaluation_results_path=evaluation_results_path,
            leaderboard_dir=root / "docs" / "_data",
            agent_share_dir=agent_share_dir,
            redteam_scorecard=evaluation_results_path / "redteam" / "scorecard.json",
            # `.bcbench` avoids colliding with agent-reserved dirs (`.claude/`, `.github/`)
            plugin_root=root / ".bcbench",
        )


@dataclass(frozen=True)
class TimeoutConfig:
    """Timeout configuration for various operations."""

    execute_query: int
    agent_execution: int
    bcal_execution: int
    filepath_identification: int

    @classmethod
    def default(cls) -> TimeoutConfig:
        """Get default timeout configuration."""
        return cls(
            # The data-query gold query is compiled, published AND run live per entry — it does more
            # than a plain app build and is slow on the insider-29 artifact, so it gets its own budget.
            execute_query=15 * 60,
            agent_execution=60 * 60,  # 60 minutes for coding agent (claude and copilot) execution
            # Total bcal CLI budget per instance.
            bcal_execution=25 * 60,
            # Context-free file-path identification; kept below the 20-min workflow step timeout
            # so a hung run fails before the CI step is force-killed.
            filepath_identification=15 * 60,
        )


@dataclass(frozen=True)
class FilePatternConfig:
    """File patterns and naming conventions."""

    trajectory_pattern: str
    instance_pattern: str
    result_pattern: str
    instruction_source_naming: str
    instructions_dirname: str
    test_project_identifiers: tuple[str, ...]
    problem_statement_readme: str
    problem_statement_dest_dir: str
    nl2al_export_subdir: str
    plugin_manifest: Path

    @classmethod
    def default(cls) -> FilePatternConfig:
        """Get default file pattern configuration."""
        return cls(
            trajectory_pattern=".traj.json",
            instance_pattern=r"^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+-[0-9]+$",
            result_pattern=".jsonl",
            instruction_source_naming="AGENTS.md",
            instructions_dirname="instructions",
            test_project_identifiers=("test", "tests"),
            problem_statement_readme="README.md",
            problem_statement_dest_dir="problem",
            nl2al_export_subdir="src",
            # Where both Copilot CLI and Claude Code look for a plugin's manifest
            plugin_manifest=Path(".claude-plugin") / "plugin.json",
        )


class JudgeConfig(BaseModel):
    """Configuration for LLM judges, read from the `judges` section of `config.yaml`."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    code_review_model: CopilotModelName = Field(validation_alias=AliasPath("judges", "code-review", "model"))
    lm_checklist_model: str = Field(min_length=1, validation_alias=AliasPath("judges", "lm-checklist", "model"))
    result_file: str = "judge_results.json"

    @classmethod
    def from_file(cls, path: Path) -> JudgeConfig:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class EnvironmentConfig:
    """Environment-specific configuration."""

    # GitHub Actions
    github_output: str | None
    github_step_summary: str | None
    github_actions: bool
    runner_debug: bool

    @classmethod
    def from_environment(cls) -> EnvironmentConfig:
        """Load configuration from environment variables."""
        return cls(
            github_output=os.getenv("GITHUB_OUTPUT"),
            github_step_summary=os.getenv("GITHUB_STEP_SUMMARY"),
            github_actions=os.getenv("GITHUB_ACTIONS") == "true",
            runner_debug=os.getenv("RUNNER_DEBUG") == "1",
        )


@dataclass(frozen=True)
class Config:
    """Centralized configuration for BC-Bench."""

    paths: PathConfig
    env: EnvironmentConfig
    timeout: TimeoutConfig
    file_patterns: FilePatternConfig
    judge: JudgeConfig

    @classmethod
    def load(cls) -> Config:
        root = _get_git_root()
        path_config = PathConfig.from_root(root)

        return cls(
            paths=path_config,
            env=EnvironmentConfig.from_environment(),
            timeout=TimeoutConfig.default(),
            file_patterns=FilePatternConfig.default(),
            judge=JudgeConfig.from_file(path_config.agent_share_dir / "config.yaml"),
        )


# Singleton instance
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config  # noqa: PLW0603
    if _config is None:
        load_dotenv()
        _config = Config.load()
    return _config
