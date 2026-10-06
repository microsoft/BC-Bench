from bcbench.categories.definition import CategoryDefinition
from bcbench.categories.nl2al.entry import NL2ALEntry
from bcbench.categories.nl2al.pipeline import NL2ALPipeline
from bcbench.results.leaderboard import JudgeBasedLeaderboardAggregate
from bcbench.results.summary import JudgeBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory

DEFINITION: CategoryDefinition[NL2ALEntry] = CategoryDefinition(
    category=EvaluationCategory.NL2AL,
    dataset_file="nl2al.jsonl",
    entry_type=NL2ALEntry,
    pipeline_type=NL2ALPipeline,
    summary_type=JudgeBasedEvaluationResultSummary,
    aggregate_type=JudgeBasedLeaderboardAggregate,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    judge="lm-checklist",
    runner="windows-latest",
    requires_container=False,
    pass_bc_credentials=True,
)
