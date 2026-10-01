from bcbench.categories.base import CategoryCapabilities, CategoryReporting, JudgeCategoryDefinition
from bcbench.config import Config
from bcbench.dataset.dataset_entry import NL2ALEntry
from bcbench.evaluate.nl2al import NL2ALPipeline
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.leaderboard import JudgeBasedLeaderboardAggregate
from bcbench.results.summary import JudgeBasedEvaluationResultSummary
from bcbench.types import EvaluationCategory


def build_definition(config: Config) -> JudgeCategoryDefinition[NL2ALEntry]:
    return JudgeCategoryDefinition(
        name=EvaluationCategory.NL2AL,
        dataset_path=config.paths.dataset_dir / "nl2al.jsonl",
        entry_class=NL2ALEntry,
        pipeline_factory=lambda: NL2ALPipeline(result_class=JudgeBasedEvaluationResult, result_suffix=config.file_patterns.result_pattern),
        capabilities=CategoryCapabilities(requires_container=False),
        reporting=CategoryReporting(
            result_class=JudgeBasedEvaluationResult,
            summary_class=JudgeBasedEvaluationResultSummary,
            aggregate_class=JudgeBasedLeaderboardAggregate,
            evaluators=("lm_checklist",),
            core_score="test_passed",
            runner="windows-latest",
        ),
        judge_model=config.judge.lm_checklist_model,
    )
