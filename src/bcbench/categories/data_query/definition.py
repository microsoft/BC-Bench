from bcbench.categories.data_query.entry import DataQueryEntry
from bcbench.categories.data_query.pipeline import DataQueryPipeline
from bcbench.categories.definition import CategoryDefinition
from bcbench.results.leaderboard import ExecutionBasedLeaderboardAggregate
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory

DEFINITION: CategoryDefinition[DataQueryEntry] = CategoryDefinition(
    category=EvaluationCategory.DATA_QUERY,
    dataset_file="dataquery.jsonl",
    entry_type=DataQueryEntry,
    pipeline_type=DataQueryPipeline,
    summary_type=ExecutionBasedEvaluationResultSummary,
    aggregate_type=ExecutionBasedLeaderboardAggregate,
    evaluators=("resolution_rate", "build_rate"),
    core_score="ResolutionRate",
    judge=None,
    runner="GitHub-BCBench",
    requires_container=True,
    pass_bc_credentials=False,
)
