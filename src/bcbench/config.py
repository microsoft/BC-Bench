"""Centralized configuration and constant management for BC-Bench."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

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
    dataset_dir: Path
    problem_statement_dir: Path
    testbed_path: Path
    ps_script_path: Path
    evaluation_results_path: Path
    leaderboard_dir: Path
    copilot_dir: Path
    agent_share_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> PathConfig:
        """Create path configuration from repository root."""
        return cls(
            bc_bench_root=root,
            dataset_dir=root / "dataset",
            dataset_path=root / "dataset" / "bcbench.jsonl",
            problem_statement_dir=root / "dataset" / "problemstatement",
            testbed_path=root.parent / "NAV",
            ps_script_path=root / "scripts",
            evaluation_results_path=root / "evaluation_results",
            leaderboard_dir=root / "docs" / "_data",
            copilot_dir=root / "src" / "bcbench" / "agent" / "copilot",
            agent_share_dir=root / "src" / "bcbench" / "agent" / "shared",
        )


@dataclass(frozen=True)
class TimeoutConfig:
    """Timeout configuration for various operations."""

    build_baseapp: int
    build_app: int
    test_execution: int
    agent_execution: int

    @classmethod
    def default(cls) -> TimeoutConfig:
        """Get default timeout configuration."""
        return cls(
            build_baseapp=30 * 60,  # 30 minutes for BaseApp compilation
            build_app=5 * 60,  # 5 minutes for application compilation
            test_execution=3 * 60,  # 3 minutes for test execution
            agent_execution=30 * 60,  # 30 minutes for coding agent (claude and copilot) execution
        )


@dataclass(frozen=True)
class FilePatternConfig:
    """File patterns and naming conventions."""

    trajectory_pattern: str
    patch_pattern: str
    instance_pattern: str
    result_pattern: str
    copilot_instruction_naming: str
    copilot_instructions_dirname: str
    copilot_instructions_pattern: str
    test_project_identifiers: tuple[str, ...]
    problem_statement_readme: str
    problem_statement_dest_dir: str

    @classmethod
    def default(cls) -> FilePatternConfig:
        """Get default file pattern configuration."""
        return cls(
            trajectory_pattern=".traj.json",
            patch_pattern=".patch",
            instance_pattern=r"^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+-[0-9]+$",
            result_pattern=".jsonl",
            copilot_instruction_naming="copilot-instructions.md",
            copilot_instructions_dirname="instructions",
            copilot_instructions_pattern="*.instructions.md",
            test_project_identifiers=("test", "tests"),
            problem_statement_readme="README.md",
            problem_statement_dest_dir="problem",
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

        return cls(
            paths=path_config,
            env=EnvironmentConfig.from_environment(),
            timeout=TimeoutConfig.default(),
            file_patterns=FilePatternConfig.default(),
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
        load_dotenv()
        _config = Config.load()
    return _config
