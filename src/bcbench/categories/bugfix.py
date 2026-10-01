from bcbench.categories.base import CategoryCoreScore, CategoryEvaluator, CategoryReporting, CategoryRunner, ExecutionCategoryDefinition
from bcbench.config import Config
from bcbench.dataset.dataset_entry import BugFixEntry
from bcbench.evaluate.bugfix import BugFixPipeline
from bcbench.results.bugfix import BugFixResult
from bcbench.results.leaderboard import ExecutionBasedLeaderboardAggregate
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory


def build_definition(config: Config) -> ExecutionCategoryDefinition[BugFixEntry]:
    return ExecutionCategoryDefinition(
        name=EvaluationCategory.BUG_FIX,
        dataset_path=config.paths.dataset_dir / "bcbench.jsonl",
        entry_class=BugFixEntry,
        pipeline_factory=lambda: BugFixPipeline(result_class=BugFixResult, result_suffix=config.file_patterns.result_pattern),
        reporting=CategoryReporting(
            result_class=BugFixResult,
            summary_class=ExecutionBasedEvaluationResultSummary,
            aggregate_class=ExecutionBasedLeaderboardAggregate,
            evaluators=(CategoryEvaluator.RESOLUTION_RATE, CategoryEvaluator.BUILD_RATE),
            core_score=CategoryCoreScore.RESOLUTION_RATE,
            runner=CategoryRunner.BC_BENCH,
        ),
    )
