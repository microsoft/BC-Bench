from bcbench.categories.base import CategoryDefinition, judge_mock_result
from bcbench.dataset.extensibility_request import ExtRequestAdvisorEntry
from bcbench.evaluate.ext_request_advisor import ExtRequestAdvisorPipeline
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.leaderboard import JudgeBasedLeaderboardAggregate
from bcbench.results.summary import JudgeBasedEvaluationResultSummary

DEFINITION = CategoryDefinition(
    dataset_filename="extensibility_request_advisor.jsonl",
    entry_class=ExtRequestAdvisorEntry,
    pipeline_factory=ExtRequestAdvisorPipeline,
    result_class=JudgeBasedEvaluationResult,
    summary_class=JudgeBasedEvaluationResultSummary,
    aggregate_class=JudgeBasedLeaderboardAggregate,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    runner="ubuntu-latest",
    requires_container=False,
    judge_model=lambda config: config.lm_checklist_model,
    mock_scenarios=("raw", "empty"),
    create_mock_result=judge_mock_result,
)
