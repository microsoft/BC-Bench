from collections.abc import Callable, Mapping
from dataclasses import dataclass

from bcbench.config import JudgeConfig
from bcbench.dataset.dataset_entry import BaseDatasetEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.results.base import BaseEvaluationResult, ExecutionBasedEvaluationResult, JudgeBasedEvaluationResult
from bcbench.results.leaderboard import LeaderboardAggregate
from bcbench.results.summary import EvaluationResultSummary
from bcbench.types import EvaluationContext


def default_prompt_context(config: Mapping[str, object]) -> dict[str, object]:
    return {"is_gold_patch": False, "is_problem_statement": False}


def execution_mock_result(context: EvaluationContext, scenario: str) -> BaseEvaluationResult:
    match scenario:
        case "success":
            return ExecutionBasedEvaluationResult.create_success(context, "MOCK_PATCH_CONTENT")
        case "build-fail":
            return ExecutionBasedEvaluationResult.create_build_failure(context, "MOCK_PATCH_CONTENT", "Mock build failure")
        case _:
            raise ValueError(f"Unknown execution scenario: {scenario}")


def judge_mock_result(context: EvaluationContext, scenario: str) -> BaseEvaluationResult:
    match scenario:
        case "raw":
            return JudgeBasedEvaluationResult.create_raw(context, "MOCK_PATCH_CONTENT")
        case "empty":
            return JudgeBasedEvaluationResult.create_empty_output(context)
        case _:
            raise ValueError(f"Unknown judge scenario: {scenario}")


@dataclass(frozen=True, kw_only=True)
class CategoryDefinition[E: BaseDatasetEntry]:
    dataset_filename: str
    entry_class: type[E]
    pipeline_factory: Callable[[], EvaluationPipeline[E]]
    result_class: type[BaseEvaluationResult]
    summary_class: type[EvaluationResultSummary]
    aggregate_class: type[LeaderboardAggregate]
    evaluators: tuple[str, ...]
    core_score: str
    runner: str
    requires_container: bool
    judge_model: Callable[[JudgeConfig], str | None]
    mock_scenarios: tuple[str, ...]
    create_mock_result: Callable[[EvaluationContext, str], BaseEvaluationResult]
    pass_on_bc_container_credentials: bool = True
    prompt_context: Callable[[Mapping[str, object]], dict[str, object]] = default_prompt_context
