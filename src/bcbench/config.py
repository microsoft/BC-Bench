"""Centralized configuration and constant management for BC-Bench."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import AliasPath, BaseModel, ConfigDict, Field

from bcbench.paths import SHARED_CONFIG_FILE
from bcbench.types import CopilotModelName

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
    redteam_scorecard: Path
    plugin_root: Path

    @classmethod
    def from_root(cls, root: Path) -> PathConfig:
        """Create path configuration from repository root."""
        evaluation_results_path = root / "evaluation_results"
        return cls(
            bc_bench_root=root,
            dataset_dir=root / "dataset",
            problem_statement_dir=root / "dataset" / "problemstatement",
            testbed_path=root.parent / "NAV",
            evaluation_results_path=evaluation_results_path,
            leaderboard_dir=root / "docs" / "_data",
            redteam_scorecard=evaluation_results_path / "redteam" / "scorecard.json",
            # `.bcbench` avoids colliding with agent-reserved dirs (`.claude/`, `.github/`)
            plugin_root=root / ".bcbench",
        )


class JudgeConfig(BaseModel):
    """Configuration for LLM judges, read from the `judges` section of `config.yaml`."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    code_review_model: CopilotModelName = Field(validation_alias=AliasPath("judges", "code-review", "model"))
    lm_checklist_model: str = Field(min_length=1, validation_alias=AliasPath("judges", "lm-checklist", "model"))

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
    judge: JudgeConfig

    @classmethod
    def load(cls) -> Config:
        root = _get_git_root()
        path_config = PathConfig.from_root(root)

        return cls(
            paths=path_config,
            env=EnvironmentConfig.from_environment(),
            judge=JudgeConfig.from_file(SHARED_CONFIG_FILE),
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
