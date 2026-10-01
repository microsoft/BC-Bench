from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from bcbench.dataset.dataset_entry import BaseDatasetEntry, RepoGroundedEntry
from bcbench.results.base import BaseEvaluationResult, ExecutionBasedEvaluationResult, JudgeScoredEvaluationResult
from bcbench.results.leaderboard import LeaderboardAggregate
from bcbench.results.summary import EvaluationResultSummary
from bcbench.types import EvaluationCategory

if TYPE_CHECKING:
    from bcbench.evaluate.base import EvaluationPipeline


class CategoryEvaluator(StrEnum):
    RESOLUTION_RATE = "resolution_rate"
    BUILD_RATE = "build_rate"
    PRE_PATCH_FAILED_RATE = "pre_patch_failed_rate"
    POST_PATCH_PASSED_RATE = "post_patch_passed_rate"
    LM_CHECKLIST = "lm_checklist"
    PRECISION_SCORE = "precision_score"
    RECALL_SCORE = "recall_score"
    F1_SCORE = "f1_score"
    VALID_REVIEW_OUTPUT = "valid_review_output"


class CategoryCoreScore(StrEnum):
    RESOLUTION_RATE = "ResolutionRate"
    TEST_PASSED = "test_passed"
    F1_SCORE = "F1Score"


class CategoryRunner(StrEnum):
    BC_BENCH = "GitHub-BCBench"
    UBUNTU = "ubuntu-latest"
    WINDOWS = "windows-latest"


class PromptContext(TypedDict):
    is_gold_patch: bool
    is_problem_statement: bool


def default_prompt_context(config: Mapping[str, object]) -> PromptContext:
    return {"is_gold_patch": False, "is_problem_statement": False}


@dataclass(frozen=True, kw_only=True)
class CategoryCapabilities:
    requires_container: bool
    pass_on_bc_container_credentials: bool = True


@dataclass(frozen=True, kw_only=True)
class CategoryReporting:
    result_class: type[BaseEvaluationResult]
    summary_class: type[EvaluationResultSummary]
    aggregate_class: type[LeaderboardAggregate]
    evaluators: tuple[CategoryEvaluator, ...]
    core_score: CategoryCoreScore
    runner: CategoryRunner


@dataclass(frozen=True, kw_only=True)
class CategoryDefinition[E: BaseDatasetEntry]:
    name: EvaluationCategory
    dataset_path: Path
    entry_class: type[E]
    pipeline_factory: Callable[[], EvaluationPipeline[E]]
    capabilities: CategoryCapabilities
    reporting: CategoryReporting
    prompt_context: Callable[[Mapping[str, object]], PromptContext] = default_prompt_context

    @property
    def requires_repo(self) -> bool:
        return issubclass(self.entry_class, RepoGroundedEntry)


@dataclass(frozen=True, kw_only=True)
class ExecutionCategoryDefinition[E: BaseDatasetEntry](CategoryDefinition[E]):
    capabilities: CategoryCapabilities = CategoryCapabilities(requires_container=True)

    def __post_init__(self) -> None:
        if not self.capabilities.requires_container:
            raise ValueError("Execution-scored categories require a container")
        if not issubclass(self.reporting.result_class, ExecutionBasedEvaluationResult):
            raise TypeError("Execution-scored categories require an execution result class")


@dataclass(frozen=True, kw_only=True)
class JudgeCategoryDefinition[E: BaseDatasetEntry](CategoryDefinition[E]):
    judge_model: str

    def __post_init__(self) -> None:
        if not self.judge_model.strip():
            raise ValueError("Judge-scored categories require a judge model")
        if not issubclass(self.reporting.result_class, JudgeScoredEvaluationResult):
            raise TypeError("Judge-scored categories require a judge result class")
