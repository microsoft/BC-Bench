from bcbench.categories.base import CategoryDefinition, judge_mock_result
from bcbench.dataset.dataset_entry import NL2ALEntry
from bcbench.evaluate.nl2al import NL2ALPipeline
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.leaderboard import JudgeBasedLeaderboardAggregate
from bcbench.results.summary import JudgeBasedEvaluationResultSummary

DEFINITION = CategoryDefinition(
    dataset_filename="nl2al.jsonl",
    entry_class=NL2ALEntry,
    pipeline_factory=NL2ALPipeline,
    result_class=JudgeBasedEvaluationResult,
    summary_class=JudgeBasedEvaluationResultSummary,
    aggregate_class=JudgeBasedLeaderboardAggregate,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    runner="windows-latest",
    requires_container=False,
    judge_model=lambda config: config.lm_checklist_model,
    mock_scenarios=("raw", "empty"),
    create_mock_result=judge_mock_result,
)
