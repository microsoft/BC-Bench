"""Centralized configuration management for BC-Bench."""

from __future__ import annotations

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

    @classmethod
    def from_root(cls, root: Path) -> PathConfig:
        """Create path configuration from repository root."""
        return cls(
            bc_bench_root=root,
            dataset_path=root / "dataset" / "bcbench_nav.jsonl",
            dataset_schema_path=root / "dataset" / "schema.json",
            nav_repo_path=root.parent / "NAV",
            ps_script_path=root / "scripts",
        )


@dataclass(frozen=True)
class EnvironmentConfig:
    """Environment-specific configuration."""

    # Business Central
    bc_container_password: str | None

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
            bc_container_password=os.getenv("BC_CONTAINER_PASSWORD"),
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

    @classmethod
    def load(cls) -> Config:
        root = _get_git_root()
        return cls(
            paths=PathConfig.from_root(root),
            env=EnvironmentConfig.from_environment(),
        )

    def resolve_password(self, password: str | None = None) -> str:
        resolved = password or self.env.bc_container_password
        if not resolved:
            raise ConfigurationError("Password required. Provide --password or set BC_CONTAINER_PASSWORD env var")
        return resolved

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
