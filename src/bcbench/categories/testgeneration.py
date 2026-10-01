from collections.abc import Mapping

from bcbench.categories.base import CategoryDefinition, execution_mock_result
from bcbench.dataset.dataset_entry import TestGenEntry
from bcbench.evaluate.testgeneration import TestGenerationPipeline
from bcbench.results.leaderboard import ExecutionBasedLeaderboardAggregate
from bcbench.results.summary import ExecutionBasedEvaluationResultSummary
from bcbench.results.testgeneration import TestGenerationResult


def prompt_context(config: Mapping[str, object]) -> dict[str, object]:
    source = config.get("test-generation-input", "problem-statement")
    return {"is_gold_patch": source in ("gold-patch", "both"), "is_problem_statement": source in ("problem-statement", "both")}


DEFINITION = CategoryDefinition(
    dataset_filename="bcbench.jsonl",
    entry_class=TestGenEntry,
    pipeline_factory=TestGenerationPipeline,
    result_class=TestGenerationResult,
    summary_class=ExecutionBasedEvaluationResultSummary,
    aggregate_class=ExecutionBasedLeaderboardAggregate,
    evaluators=("resolution_rate", "build_rate", "pre_patch_failed_rate", "post_patch_passed_rate"),
    core_score="ResolutionRate",
    runner="GitHub-BCBench",
    requires_container=True,
    judge_model=lambda config: None,
    mock_scenarios=("success", "build-fail"),
    create_mock_result=execution_mock_result,
    prompt_context=prompt_context,
)
