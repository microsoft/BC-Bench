from bcbench.categories.base import CategoryDefinition, execution_mock_result
from bcbench.dataset.dataset_entry import DataQueryEntry
from bcbench.evaluate.dataquery import DataQueryPipeline
from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.results.leaderboard import ExecutionBasedLeaderboardAggregate
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary

DEFINITION = CategoryDefinition(
    dataset_filename="dataquery.jsonl",
    entry_class=DataQueryEntry,
    pipeline_factory=DataQueryPipeline,
    result_class=ExecutionBasedEvaluationResult,
    summary_class=ExecutionBasedEvaluationResultSummary,
    aggregate_class=ExecutionBasedLeaderboardAggregate,
    evaluators=("resolution_rate", "build_rate"),
    core_score="ResolutionRate",
    runner="GitHub-BCBench",
    requires_container=True,
    pass_on_bc_container_credentials=False,
    judge_model=lambda config: None,
    mock_scenarios=("success", "build-fail"),
    create_mock_result=execution_mock_result,
)
