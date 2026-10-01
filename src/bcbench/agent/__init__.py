"""Agent module for BC-Bench."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from bcbench.agent.bcal import BCalBackendConfig, run_bcal_agent
    from bcbench.agent.claude import get_claude_version, run_claude_code
    from bcbench.agent.copilot import get_copilot_version, run_copilot_agent
    from bcbench.dataset import BaseDatasetEntry
    from bcbench.types import EvaluationCategory, ExperimentConfiguration, PRReviewMetrics

_LAZY_EXPORTS = {
    "BCalBackendConfig": "bcbench.agent.bcal",
    "get_claude_version": "bcbench.agent.claude",
    "get_copilot_version": "bcbench.agent.copilot",
    "run_bcal_agent": "bcbench.agent.bcal",
    "run_claude_code": "bcbench.agent.claude",
    "run_copilot_agent": "bcbench.agent.copilot",
}


def __getattr__(name: str) -> object:
    if name in _LAZY_EXPORTS:
        return getattr(import_module(_LAZY_EXPORTS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_pr_review_version(engine_path: Path | None) -> str:
    from bcbench.agent.pr_review import get_pr_review_version as get_version

    return get_version(engine_path)


def run_pr_review_agent(
    entry: BaseDatasetEntry,
    model: str,
    category: EvaluationCategory,
    repo_path: Path,
    output_dir: Path,
    engine_path: Path | None = None,
    min_severity: str | None = None,
) -> tuple[PRReviewMetrics, ExperimentConfiguration]:
    from bcbench.agent.pr_review import run_pr_review_agent as run_agent

    return run_agent(
        entry=entry,
        model=model,
        category=category,
        repo_path=repo_path,
        output_dir=output_dir,
        engine_path=engine_path,
        min_severity=min_severity,
    )


__all__ = ["BCalBackendConfig", "get_claude_version", "get_copilot_version", "get_pr_review_version", "run_bcal_agent", "run_claude_code", "run_copilot_agent", "run_pr_review_agent"]
