import logging
from typing import Annotated, override

from bcbench_core.agent.harness import AgentResult
from bcbench_core.evaluation import Category
from bcbench_core.exceptions import EmptyDiffError
from bcbench_core.git import stage_and_get_diff
from pydantic import Field

from bcbench.categories.definition import CategoryDefinition
from bcbench.dataset import RepoGroundedEntry
from bcbench.operations import copy_problem_statement_folder, set_runtime_version, setup_repo_prebuild
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.leaderboard import JudgeBasedLeaderboardAggregate
from bcbench.results.summary import JudgeBasedEvaluationResultSummary
from bcbench.types import Checklist, ChecklistAssertion, DatasetTier, EvaluationCategory, EvaluationContext

logger = logging.getLogger(__name__)

__all__ = ["DEFINITION", "ExtRequestImplementCategory", "ExtRequestImplementEntry"]


class ExtRequestImplementEntry(RepoGroundedEntry):
    """Dataset entry for the extensibility-request-implement category — implement an approved extensibility request in AL.

    Judge-based (no build, no tests). The agent reads the extensibility request (provided as plain
    text) and adds the requested extension point (typically an integration event) to the existing repo
    checked out at `base_commit`. The agent's diff is graded by an LLM judge against `expected`, which
    encodes both fidelity to the gold fix (`patch`) and correct propagation across the expected
    W1 + country/region layer files.
    """

    # LLM-judge checklist: expected event/signature/placement and expected layer propagation.
    expected: Annotated[list[ChecklistAssertion], Field(min_length=1)]

    @override
    def get_expected_output(self) -> Checklist:
        return {"assertions": self.expected}


class ExtRequestImplementCategory(Category[EvaluationContext[ExtRequestImplementEntry], JudgeBasedEvaluationResult]):
    """Implement an extensibility request as an AL change.

    Judge-based: no BC container, no build, no tests. The repo is checked out at the entry's base
    commit and the agent adds the requested extension point. The resulting diff is scored downstream
    by an LLM judge against the entry checklist.
    """

    @override
    def prepare_workspace(self, task: EvaluationContext[ExtRequestImplementEntry]) -> None:
        setup_repo_prebuild(task.entry, task.repo_path)
        copy_problem_statement_folder(task.entry, task.repo_path)
        set_runtime_version(task.repo_path, task.entry.project_paths)

    @override
    def prepare(self, task: EvaluationContext[ExtRequestImplementEntry]) -> None:
        self.prepare_workspace(task)

    @override
    def grade(self, task: EvaluationContext[ExtRequestImplementEntry], result: AgentResult) -> JudgeBasedEvaluationResult:
        try:
            generated_patch = stage_and_get_diff(task.repo_path, exclude=("**/app.json", "*.docx", "*.md"))
        except EmptyDiffError:
            logger.warning(f"Agent produced no changes for {task.entry.instance_id}")
            return JudgeBasedEvaluationResult.create_empty_output(task, result)

        logger.info(f"Saved raw extensibility-request-implement result for {task.entry.instance_id} (scoring pending)")
        return JudgeBasedEvaluationResult.create_raw(task, result, output=generated_patch)


DEFINITION: CategoryDefinition[ExtRequestImplementEntry] = CategoryDefinition(
    category=EvaluationCategory.EXT_REQUEST_IMPLEMENT,
    dataset_files={DatasetTier.GOLD: "extensibility_request_implement.jsonl"},
    entry_type=ExtRequestImplementEntry,
    result_type=JudgeBasedEvaluationResult,
    summary_type=JudgeBasedEvaluationResultSummary,
    aggregate_type=JudgeBasedLeaderboardAggregate,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    judge="lm-checklist",
    runner="ubuntu-latest",
    requires_container=False,
    pass_bc_credentials=True,
    make=lambda _agent_config: ExtRequestImplementCategory(),
)
