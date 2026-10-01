from importlib import import_module
from typing import TYPE_CHECKING

from bcbench.results.base import ExecutionBasedEvaluationResult, JudgeBasedEvaluationResult
from bcbench.results.bceval_export import write_bceval_results
from bcbench.results.display import create_console_summary, create_github_job_summary
from bcbench.results.leaderboard import (
    CodeReviewLeaderboardAggregate,
    ExecutionBasedLeaderboardAggregate,
    Leaderboard,
    LeaderboardAggregate,
)
from bcbench.results.metrics import bootstrap_ci, f_beta_score, pass_at_k, pass_hat_k
from bcbench.results.summary import (
    BaseEvaluationResult,
    EvaluationResultSummary,
    ExecutionBasedEvaluationResultSummary,
    JudgeBasedEvaluationResultSummary,
)

if TYPE_CHECKING:
    from bcbench.results.codereview import CodeReviewResult, CodeReviewResultSummary


def __getattr__(name: str) -> object:
    if name in {"CodeReviewResult", "CodeReviewResultSummary"}:
        return getattr(import_module("bcbench.results.codereview"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BaseEvaluationResult",
    "CodeReviewLeaderboardAggregate",
    "CodeReviewResult",
    "CodeReviewResultSummary",
    "EvaluationResultSummary",
    "ExecutionBasedEvaluationResult",
    "ExecutionBasedEvaluationResultSummary",
    "ExecutionBasedLeaderboardAggregate",
    "JudgeBasedEvaluationResult",
    "JudgeBasedEvaluationResultSummary",
    "Leaderboard",
    "LeaderboardAggregate",
    "bootstrap_ci",
    "create_console_summary",
    "create_github_job_summary",
    "f_beta_score",
    "pass_at_k",
    "pass_hat_k",
    "write_bceval_results",
]
