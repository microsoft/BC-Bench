"""extensibility-request-advisor: offline single-shot proxy for the interactive extensibility advisor.

The prompt supplies the complete scenario and GitHub submission is disabled. The agent writes its decision to `advisor_result.json`; only that raw output is kept here, and it is scored
downstream by the LMChecklist judge against the entry's `expected` checklist.
"""

import logging
from typing import Annotated, override

from bcbench_core.agent.harness import AgentResult
from bcbench_core.evaluation import Category
from pydantic import Field

from bcbench.categories.definition import CategoryDefinition
from bcbench.dataset import RepoGroundedEntry
from bcbench.operations import setup_repo_prebuild
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.leaderboard import JudgeBasedLeaderboardAggregate
from bcbench.results.summary import JudgeBasedEvaluationResultSummary
from bcbench.types import Checklist, ChecklistAssertion, DatasetTier, EvaluationCategory, EvaluationContext

logger = logging.getLogger(__name__)

__all__ = ["ADVISOR_RESULT_FILE", "DEFINITION", "ExtRequestAdvisorCategory", "ExtRequestAdvisorEntry"]

ADVISOR_RESULT_FILE = "advisor_result.json"


class ExtRequestAdvisorEntry(RepoGroundedEntry):
    """Single-shot proxy for preparing a Business Central extensibility request."""

    patch: str | None = None

    title: Annotated[str, Field(min_length=1)]
    description: Annotated[str, Field(min_length=1)]
    comments: str = ""
    expected: Annotated[list[ChecklistAssertion], Field(min_length=1)]

    @override
    def get_task(self) -> str:
        sections = [f"# {self.title}", "", self.description.rstrip()]
        if self.comments.strip():
            sections += ["", "## Additional requester context", "", self.comments.rstrip()]
        return "\n".join(sections)

    @override
    def get_expected_output(self) -> Checklist:
        return {"assertions": self.expected}


class ExtRequestAdvisorCategory(Category[EvaluationContext[ExtRequestAdvisorEntry], JudgeBasedEvaluationResult]):
    """No BC container, no build, no tests."""

    @override
    def prepare_workspace(self, task: EvaluationContext[ExtRequestAdvisorEntry]) -> None:
        setup_repo_prebuild(task.entry, task.repo_path)
        (task.repo_path / ADVISOR_RESULT_FILE).unlink(missing_ok=True)

    @override
    def prepare(self, task: EvaluationContext[ExtRequestAdvisorEntry]) -> None:
        self.prepare_workspace(task)

    @override
    def grade(self, task: EvaluationContext[ExtRequestAdvisorEntry], result: AgentResult) -> JudgeBasedEvaluationResult:
        result_path = task.repo_path / ADVISOR_RESULT_FILE
        raw = result_path.read_text(encoding="utf-8").strip() if result_path.exists() else ""

        if not raw:
            logger.warning(f"Agent produced no {ADVISOR_RESULT_FILE} for {task.entry.instance_id}")
            return JudgeBasedEvaluationResult.create_empty_output(task, result)

        logger.info(f"Saved raw extensibility-request-advisor result for {task.entry.instance_id} (scoring pending)")
        return JudgeBasedEvaluationResult.create_raw(task, result, output=raw)


DEFINITION: CategoryDefinition[ExtRequestAdvisorEntry] = CategoryDefinition(
    category=EvaluationCategory.EXT_REQUEST_ADVISOR,
    dataset_files={DatasetTier.GOLD: "extensibility_request_advisor.jsonl"},
    entry_type=ExtRequestAdvisorEntry,
    result_type=JudgeBasedEvaluationResult,
    summary_type=JudgeBasedEvaluationResultSummary,
    aggregate_type=JudgeBasedLeaderboardAggregate,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    judge="lm-checklist",
    runner="ubuntu-latest",
    requires_container=False,
    pass_bc_credentials=True,
    make=lambda _agent_config: ExtRequestAdvisorCategory(),
)
