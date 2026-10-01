from bcbench.categories.base import CategoryDefinition
from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.results.codereview import CodeReviewResult, CodeReviewResultSummary
from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate
from bcbench.types import EvaluationContext


def create_mock_result(context: EvaluationContext, scenario: str) -> CodeReviewResult:
    match scenario:
        case "invalid":
            return CodeReviewResult.create_invalid(context, output="MOCK_INVALID_REVIEW_OUTPUT", expected_comments=[])
        case "valid":
            return CodeReviewResult.create(context, output="[]", expected_comments=[], generated_comments=[], matched_pairs=[], ignored_comments=[], ignored_matched_pairs=[])
        case _:
            raise ValueError(f"Unknown review scenario: {scenario}")


DEFINITION = CategoryDefinition(
    dataset_filename="codereview.jsonl",
    entry_class=CodeReviewEntry,
    pipeline_factory=CodeReviewPipeline,
    result_class=CodeReviewResult,
    summary_class=CodeReviewResultSummary,
    aggregate_class=CodeReviewLeaderboardAggregate,
    evaluators=("precision_score", "recall_score", "f1_score", "valid_review_output"),
    core_score="F1Score",
    runner="ubuntu-latest",
    requires_container=False,
    judge_model=lambda config: config.code_review_model,
    mock_scenarios=("invalid", "valid"),
    create_mock_result=create_mock_result,
)
