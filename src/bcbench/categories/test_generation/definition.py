from bcbench.categories.definition import CategoryDefinition
from bcbench.categories.test_generation.pipeline import TestGenerationPipeline
from bcbench.dataset import TestGenEntry
from bcbench.results.leaderboard import ExecutionBasedLeaderboardAggregate
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory

DEFINITION: CategoryDefinition[TestGenEntry] = CategoryDefinition(
    category=EvaluationCategory.TEST_GENERATION,
    dataset_file="bcbench.jsonl",
    entry_type=TestGenEntry,
    pipeline_type=TestGenerationPipeline,
    summary_type=ExecutionBasedEvaluationResultSummary,
    aggregate_type=ExecutionBasedLeaderboardAggregate,
    evaluators=("resolution_rate", "build_rate", "pre_patch_failed_rate", "post_patch_passed_rate"),
    core_score="ResolutionRate",
    judge=None,
    runner="GitHub-BCBench",
    requires_container=True,
    pass_bc_credentials=True,
)
