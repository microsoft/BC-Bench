from bcbench.categories.definition import CategoryDefinition
from bcbench.categories.ext_request_triage.entry import ExtRequestTriageEntry
from bcbench.categories.ext_request_triage.pipeline import ExtRequestTriagePipeline
from bcbench.results.leaderboard import JudgeBasedLeaderboardAggregate
from bcbench.results.summary import JudgeBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory

DEFINITION: CategoryDefinition[ExtRequestTriageEntry] = CategoryDefinition(
    category=EvaluationCategory.EXT_REQUEST_TRIAGE,
    dataset_file="extensibility_request_triage.jsonl",
    entry_type=ExtRequestTriageEntry,
    pipeline_type=ExtRequestTriagePipeline,
    summary_type=JudgeBasedEvaluationResultSummary,
    aggregate_type=JudgeBasedLeaderboardAggregate,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    judge="lm-checklist",
    runner="ubuntu-latest",
    requires_container=False,
    pass_bc_credentials=True,
)
