from bcbench.categories.definition import CategoryDefinition
from bcbench.categories.ext_request_implement.entry import ExtRequestImplementEntry
from bcbench.categories.ext_request_implement.pipeline import ExtRequestImplementPipeline
from bcbench.results.leaderboard import JudgeBasedLeaderboardAggregate
from bcbench.results.summary import JudgeBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory

DEFINITION: CategoryDefinition[ExtRequestImplementEntry] = CategoryDefinition(
    category=EvaluationCategory.EXT_REQUEST_IMPLEMENT,
    dataset_file="extensibility_request_implement.jsonl",
    entry_type=ExtRequestImplementEntry,
    pipeline_type=ExtRequestImplementPipeline,
    summary_type=JudgeBasedEvaluationResultSummary,
    aggregate_type=JudgeBasedLeaderboardAggregate,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    judge="lm-checklist",
    runner="ubuntu-latest",
    requires_container=False,
    pass_bc_credentials=True,
)
