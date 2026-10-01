from bcbench.categories.base import CategoryCapabilities, CategoryCoreScore, CategoryEvaluator, CategoryReporting, CategoryRunner, JudgeCategoryDefinition
from bcbench.config import Config
from bcbench.dataset.extensibility_request import ExtRequestTriageEntry
from bcbench.evaluate.ext_request_triage import ExtRequestTriagePipeline
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.leaderboard import JudgeBasedLeaderboardAggregate
from bcbench.results.summary import JudgeBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory


def build_definition(config: Config) -> JudgeCategoryDefinition[ExtRequestTriageEntry]:
    return JudgeCategoryDefinition(
        name=EvaluationCategory.EXT_REQUEST_TRIAGE,
        dataset_path=config.paths.dataset_dir / "extensibility_request_triage.jsonl",
        entry_class=ExtRequestTriageEntry,
        pipeline_factory=lambda: ExtRequestTriagePipeline(result_class=JudgeBasedEvaluationResult, result_suffix=config.file_patterns.result_pattern),
        capabilities=CategoryCapabilities(requires_container=False),
        reporting=CategoryReporting(
            result_class=JudgeBasedEvaluationResult,
            summary_class=JudgeBasedEvaluationResultSummary,
            aggregate_class=JudgeBasedLeaderboardAggregate,
            evaluators=(CategoryEvaluator.LM_CHECKLIST,),
            core_score=CategoryCoreScore.TEST_PASSED,
            runner=CategoryRunner.UBUNTU,
        ),
        judge_model=config.judge.lm_checklist_model,
    )
