from bcbench.categories.base import CategoryCapabilities, CategoryReporting, ExecutionCategoryDefinition
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
        capabilities=CategoryCapabilities(requires_container=True),
        reporting=CategoryReporting(
            result_class=BugFixResult,
            summary_class=ExecutionBasedEvaluationResultSummary,
            aggregate_class=ExecutionBasedLeaderboardAggregate,
            evaluators=("resolution_rate", "build_rate"),
            core_score="ResolutionRate",
            runner="GitHub-BCBench",
        ),
    )
