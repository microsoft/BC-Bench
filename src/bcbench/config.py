"""Centralized configuration and constant management for BC-Bench."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast, get_args

import yaml
from dotenv import load_dotenv

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
    ps_script_path: Path
    evaluation_results_path: Path
    leaderboard_dir: Path
    agent_share_dir: Path
    bc_artifacts_cache: Path
    redteam_scorecard: Path
    plugin_root: Path
    harms_results: Path

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
            ps_script_path=root / "scripts",
            evaluation_results_path=evaluation_results_path,
            leaderboard_dir=root / "docs" / "_data",
            agent_share_dir=agent_share_dir,
            bc_artifacts_cache=Path(r"C:\bcartifacts.cache"),
            redteam_scorecard=evaluation_results_path / "redteam" / "scorecard.json",
            # `.bcbench` avoids colliding with agent-reserved dirs (`.claude/`, `.github/`)
            plugin_root=root / ".bcbench",
            harms_results=evaluation_results_path / "harms",
        )


@dataclass(frozen=True)
class TimeoutConfig:
    """Timeout configuration for various operations."""

    build_baseapp: int
    build_app: int
    test_execution: int
    agent_execution: int
    bcal_execution: int
    filepath_identification: int

    @classmethod
    def default(cls) -> TimeoutConfig:
        """Get default timeout configuration."""
        return cls(
            build_baseapp=30 * 60,  # 30 minutes for BaseApp compilation
            build_app=5 * 60,  # 5 minutes for application compilation
            test_execution=3 * 60,  # 3 minutes for test execution
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
    patch_pattern: str
    instance_pattern: str
    result_pattern: str
    instruction_source_naming: str
    instructions_dirname: str
    test_project_identifiers: tuple[str, ...]
    problem_statement_readme: str
    problem_statement_dest_dir: str
    alpackages_dirname: str
    nl2al_export_subdir: str
    plugin_manifest: Path

    @classmethod
    def default(cls) -> FilePatternConfig:
        """Get default file pattern configuration."""
        return cls(
            trajectory_pattern=".traj.json",
            patch_pattern=".patch",
            instance_pattern=r"^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+-[0-9]+$",
            result_pattern=".jsonl",
            instruction_source_naming="AGENTS.md",
            instructions_dirname="instructions",
            test_project_identifiers=("test", "tests"),
            problem_statement_readme="README.md",
            problem_statement_dest_dir="problem",
            alpackages_dirname=".alpackages",
            nl2al_export_subdir="src",
            # Where both Copilot CLI and Claude Code look for a plugin's manifest
            plugin_manifest=Path(".claude-plugin") / "plugin.json",
        )


@dataclass(frozen=True)
class JudgeConfig:
    """Configuration for LLM judges."""

    code_review_model: CopilotModelName
    lm_checklist_model: str
    result_file: str

    @classmethod
    def from_file(cls, path: Path) -> JudgeConfig:
        shared_config = yaml.safe_load(path.read_text(encoding="utf-8"))
        code_review_model: str = shared_config["judges"]["code-review"]["model"]
        lm_checklist_model: str = shared_config["judges"]["lm-checklist"]["model"]

        if not all(model.strip() for model in (code_review_model, lm_checklist_model)):
            raise ValueError("Judge models must be non-empty strings")

        if code_review_model not in get_args(CopilotModelName):
            raise ValueError(f"Unknown code-review judge model {code_review_model!r} in {path}")

        return cls(
            code_review_model=cast(CopilotModelName, code_review_model),
            lm_checklist_model=lm_checklist_model,
            result_file="judge_results.json",
        )


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
