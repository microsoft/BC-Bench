from bcbench.categories.base import CategoryCapabilities, CategoryCoreScore, CategoryEvaluator, CategoryReporting, CategoryRunner, ExecutionCategoryDefinition
from bcbench.config import Config
from bcbench.dataset.dataset_entry import DataQueryEntry
from bcbench.evaluate.dataquery import DataQueryPipeline
from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.results.leaderboard import ExecutionBasedLeaderboardAggregate
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory


def build_definition(config: Config) -> ExecutionCategoryDefinition[DataQueryEntry]:
    return ExecutionCategoryDefinition(
        name=EvaluationCategory.DATA_QUERY,
        dataset_path=config.paths.dataset_dir / "dataquery.jsonl",
        entry_class=DataQueryEntry,
        pipeline_factory=lambda: DataQueryPipeline(result_class=ExecutionBasedEvaluationResult, result_suffix=config.file_patterns.result_pattern),
        capabilities=CategoryCapabilities(requires_container=True, pass_on_bc_container_credentials=False),
        reporting=CategoryReporting(
            result_class=ExecutionBasedEvaluationResult,
            summary_class=ExecutionBasedEvaluationResultSummary,
            aggregate_class=ExecutionBasedLeaderboardAggregate,
            evaluators=(CategoryEvaluator.RESOLUTION_RATE, CategoryEvaluator.BUILD_RATE),
            core_score=CategoryCoreScore.RESOLUTION_RATE,
            runner=CategoryRunner.BC_BENCH,
        ),
    )
