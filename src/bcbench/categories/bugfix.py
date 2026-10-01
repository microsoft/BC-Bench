from bcbench.categories.base import CategoryDefinition, execution_mock_result
from bcbench.dataset.dataset_entry import BugFixEntry
from bcbench.evaluate.bugfix import BugFixPipeline
from bcbench.results.bugfix import BugFixResult
from bcbench.results.leaderboard import ExecutionBasedLeaderboardAggregate
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary

DEFINITION = CategoryDefinition(
    dataset_filename="bcbench.jsonl",
    entry_class=BugFixEntry,
    pipeline_factory=BugFixPipeline,
    result_class=BugFixResult,
    summary_class=ExecutionBasedEvaluationResultSummary,
    aggregate_class=ExecutionBasedLeaderboardAggregate,
    evaluators=("resolution_rate", "build_rate"),
    core_score="ResolutionRate",
    runner="GitHub-BCBench",
    requires_container=True,
    judge_model=lambda config: None,
    mock_scenarios=("success", "build-fail"),
    create_mock_result=execution_mock_result,
)
