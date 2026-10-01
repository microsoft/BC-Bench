from collections.abc import Callable
from pathlib import Path

from bcbench.categories.base import CategoryCapabilities, CategoryReporting, JudgeCategoryDefinition
from bcbench.categories.code_review.entry import CodeReviewEntry
from bcbench.categories.code_review.pipeline import CodeReviewPipeline
from bcbench.categories.code_review.prompt import prompt_context
from bcbench.categories.code_review.results import CodeReviewResult, CodeReviewResultSummary
from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate
from bcbench.types import EvaluationCategory


def build_definition(*, dataset_path: Path, pipeline_factory: Callable[[], CodeReviewPipeline], judge_model: str) -> JudgeCategoryDefinition[CodeReviewEntry]:
    return JudgeCategoryDefinition(
        name=EvaluationCategory.CODE_REVIEW,
        dataset_path=dataset_path,
        entry_class=CodeReviewEntry,
        pipeline_factory=pipeline_factory,
        capabilities=CategoryCapabilities(requires_container=False),
        reporting=CategoryReporting(
            result_class=CodeReviewResult,
            summary_class=CodeReviewResultSummary,
            aggregate_class=CodeReviewLeaderboardAggregate,
            evaluators=("precision_score", "recall_score", "f1_score", "valid_review_output"),
            core_score="F1Score",
            runner="ubuntu-latest",
        ),
        judge_model=judge_model,
        prompt_context=prompt_context,
    )
