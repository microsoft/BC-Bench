from bcbench.categories.bug_fix.pipeline import BugFixPipeline
from bcbench.categories.definition import CategoryDefinition
from bcbench.dataset import BugFixEntry
from bcbench.results.leaderboard import ExecutionBasedLeaderboardAggregate
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory

DEFINITION: CategoryDefinition[BugFixEntry] = CategoryDefinition(
    category=EvaluationCategory.BUG_FIX,
    dataset_file="bcbench.jsonl",
    entry_type=BugFixEntry,
    pipeline_type=BugFixPipeline,
    summary_type=ExecutionBasedEvaluationResultSummary,
    aggregate_type=ExecutionBasedLeaderboardAggregate,
    evaluators=("resolution_rate", "build_rate"),
    core_score="ResolutionRate",
    judge=None,
    runner="GitHub-BCBench",
    requires_container=True,
    pass_bc_credentials=True,
)
