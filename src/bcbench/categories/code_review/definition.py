from bcbench.categories.definition import CategoryDefinition
from bcbench.dataset import CodeReviewEntry
from bcbench.types import EvaluationCategory

DEFINITION = CategoryDefinition(
    category=EvaluationCategory.CODE_REVIEW,
    dataset_file="codereview.jsonl",
    entry_type=CodeReviewEntry,
    evaluators=("precision_score", "recall_score", "f1_score", "valid_review_output"),
    core_score="F1Score",
    runner="ubuntu-latest",
    requires_container=False,
    pass_bc_credentials=True,
)
