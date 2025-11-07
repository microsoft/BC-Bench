"""Centralized configuration and constant management for BC-Bench."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from bcbench.exceptions import ConfigurationError

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
    dataset_path: Path
    dataset_schema_path: Path
    nav_repo_path: Path
    ps_script_path: Path
    evaluation_results_path: Path
    leaderboard_path: Path

    @classmethod
    def from_root(cls, root: Path) -> PathConfig:
        """Create path configuration from repository root."""
        return cls(
            bc_bench_root=root,
            dataset_path=root / "dataset" / "bcbench_nav.jsonl",
            dataset_schema_path=root / "dataset" / "schema.json",
            nav_repo_path=root.parent / "NAV",
            ps_script_path=root / "scripts",
            evaluation_results_path=root / "evaluation_results",
            leaderboard_path=root / "docs" / "_data" / "leaderboard.json",
        )


@dataclass(frozen=True)
class TimeoutConfig:
    """Timeout configuration for various operations."""

    build_baseapp: int
    build_app: int
    test_execution: int
    github_copilot_cli: int

    @classmethod
    def default(cls) -> TimeoutConfig:
        """Get default timeout configuration."""
        return cls(
            build_baseapp=25 * 60,  # 25 minutes for BaseApp compilation
            build_app=5 * 60,  # 5 minutes for application compilation
            test_execution=3 * 60,  # 3 minutes for test execution
            github_copilot_cli=20 * 60,  # 20 minutes for GitHub Copilot CLI execution
        )


@dataclass(frozen=True)
class FilePatternConfig:
    """File patterns and naming conventions."""

    trajectory_pattern: str
    patch_pattern: str
    instance_pattern: str
    result_pattern: str

    @classmethod
    def default(cls, instance_pattern: str) -> FilePatternConfig:
        """Get default file pattern configuration."""
        return cls(
            trajectory_pattern=".traj.json",
            patch_pattern=".patch",
            instance_pattern=instance_pattern,
            result_pattern=".jsonl",
        )


@dataclass(frozen=True)
class EnvironmentConfig:
    """Environment-specific configuration."""

    # Azure DevOps
    ado_token: str | None

    # GitHub Actions
    github_output: str | None
    github_step_summary: str | None
    github_actions: bool
    runner_debug: bool

    @classmethod
    def from_environment(cls) -> EnvironmentConfig:
        """Load configuration from environment variables."""
        return cls(
            ado_token=os.getenv("ADO_TOKEN"),
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

    @classmethod
    def load(cls) -> Config:
        root = _get_git_root()
        path_config = PathConfig.from_root(root)

        with open(path_config.dataset_schema_path) as f:
            schema = json.load(f)

        instance_pattern = schema.get("properties", {}).get("instance_id", {}).get("pattern")

        return cls(
            paths=path_config,
            env=EnvironmentConfig.from_environment(),
            timeout=TimeoutConfig.default(),
            file_patterns=FilePatternConfig.default(instance_pattern),
        )

    def resolve_ado_token(self) -> str:
        if not self.env.ado_token:
            raise ConfigurationError("ADO_TOKEN environment variable is required")
        return self.env.ado_token


# Singleton instance
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config  # noqa: PLW0603
    if _config is None:
        _config = Config.load()
    return _config
