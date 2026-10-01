from bcbench.categories.base import CategoryCapabilities, CategoryReporting, JudgeCategoryDefinition
from bcbench.config import Config
from bcbench.dataset.extensibility_request import ExtRequestImplementEntry
from bcbench.evaluate.ext_request_implement import ExtRequestImplementPipeline
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.leaderboard import JudgeBasedLeaderboardAggregate
from bcbench.results.summary import JudgeBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory


def build_definition(config: Config) -> JudgeCategoryDefinition[ExtRequestImplementEntry]:
    return JudgeCategoryDefinition(
        name=EvaluationCategory.EXT_REQUEST_IMPLEMENT,
        dataset_path=config.paths.dataset_dir / "extensibility_request_implement.jsonl",
        entry_class=ExtRequestImplementEntry,
        pipeline_factory=lambda: ExtRequestImplementPipeline(result_class=JudgeBasedEvaluationResult, result_suffix=config.file_patterns.result_pattern),
        capabilities=CategoryCapabilities(requires_container=False),
        reporting=CategoryReporting(
            result_class=JudgeBasedEvaluationResult,
            summary_class=JudgeBasedEvaluationResultSummary,
            aggregate_class=JudgeBasedLeaderboardAggregate,
            evaluators=("lm_checklist",),
            core_score="test_passed",
            runner="ubuntu-latest",
        ),
        judge_model=config.judge.lm_checklist_model,
    )
