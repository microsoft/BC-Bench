from bcbench.categories.definition import CategoryDefinition
from bcbench.categories.ext_request_advisor.entry import ExtRequestAdvisorEntry
from bcbench.categories.ext_request_advisor.pipeline import ExtRequestAdvisorPipeline
from bcbench.results.leaderboard import JudgeBasedLeaderboardAggregate
from bcbench.results.summary import JudgeBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory

DEFINITION: CategoryDefinition[ExtRequestAdvisorEntry] = CategoryDefinition(
    category=EvaluationCategory.EXT_REQUEST_ADVISOR,
    dataset_file="extensibility_request_advisor.jsonl",
    entry_type=ExtRequestAdvisorEntry,
    pipeline_type=ExtRequestAdvisorPipeline,
    summary_type=JudgeBasedEvaluationResultSummary,
    aggregate_type=JudgeBasedLeaderboardAggregate,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    judge="lm-checklist",
    runner="ubuntu-latest",
    requires_container=False,
    pass_bc_credentials=True,
)
