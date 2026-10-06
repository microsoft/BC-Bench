from bcbench.categories.code_review.entry import CodeReviewEntry
from bcbench.categories.code_review.pipeline import CodeReviewPipeline
from bcbench.categories.code_review.result import CodeReviewLeaderboardAggregate, CodeReviewResultSummary
from bcbench.categories.definition import CategoryDefinition
from bcbench.types import EvaluationCategory

DEFINITION: CategoryDefinition[CodeReviewEntry] = CategoryDefinition(
    category=EvaluationCategory.CODE_REVIEW,
    dataset_file="codereview.jsonl",
    entry_type=CodeReviewEntry,
    pipeline_type=CodeReviewPipeline,
    summary_type=CodeReviewResultSummary,
    aggregate_type=CodeReviewLeaderboardAggregate,
    evaluators=("precision_score", "recall_score", "f1_score", "valid_review_output"),
    core_score="F1Score",
    judge="code-review",
    runner="ubuntu-latest",
    requires_container=False,
    pass_bc_credentials=True,
)
