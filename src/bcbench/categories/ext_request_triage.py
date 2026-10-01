from bcbench.categories.base import CategoryDefinition, judge_mock_result
from bcbench.dataset.extensibility_request import ExtRequestTriageEntry
from bcbench.evaluate.ext_request_triage import ExtRequestTriagePipeline
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.leaderboard import JudgeBasedLeaderboardAggregate
from bcbench.results.summary import JudgeBasedEvaluationResultSummary

DEFINITION = CategoryDefinition(
    dataset_filename="extensibility_request_triage.jsonl",
    entry_class=ExtRequestTriageEntry,
    pipeline_factory=ExtRequestTriagePipeline,
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
