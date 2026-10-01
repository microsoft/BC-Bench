from collections.abc import Mapping

from bcbench.categories.base import CategoryCoreScore, CategoryEvaluator, CategoryReporting, CategoryRunner, ExecutionCategoryDefinition, PromptContext
from bcbench.config import Config
from bcbench.dataset.dataset_entry import TestGenEntry
from bcbench.evaluate.testgeneration import TestGenerationPipeline
from bcbench.results.leaderboard import ExecutionBasedLeaderboardAggregate
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary
from bcbench.results.testgeneration import TestGenerationResult
from bcbench.types import EvaluationCategory


def prompt_context(config: Mapping[str, object]) -> PromptContext:
    source = config.get("test-generation-input", "problem-statement")
    return {"is_gold_patch": source in ("gold-patch", "both"), "is_problem_statement": source in ("problem-statement", "both")}


def build_definition(config: Config) -> ExecutionCategoryDefinition[TestGenEntry]:
    return ExecutionCategoryDefinition(
        name=EvaluationCategory.TEST_GENERATION,
        dataset_path=config.paths.dataset_dir / "bcbench.jsonl",
        entry_class=TestGenEntry,
        pipeline_factory=lambda: TestGenerationPipeline(result_class=TestGenerationResult, result_suffix=config.file_patterns.result_pattern),
        reporting=CategoryReporting(
            result_class=TestGenerationResult,
            summary_class=ExecutionBasedEvaluationResultSummary,
            aggregate_class=ExecutionBasedLeaderboardAggregate,
            evaluators=(CategoryEvaluator.RESOLUTION_RATE, CategoryEvaluator.BUILD_RATE, CategoryEvaluator.PRE_PATCH_FAILED_RATE, CategoryEvaluator.POST_PATCH_PASSED_RATE),
            core_score=CategoryCoreScore.RESOLUTION_RATE,
            runner=CategoryRunner.BC_BENCH,
        ),
        prompt_context=prompt_context,
    )
