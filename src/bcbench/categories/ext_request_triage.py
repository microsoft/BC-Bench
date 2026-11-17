"""extensibility-request-triage: triage a single extensibility request.

The agent runs the `extensibility-request-triage` custom agent (instructions-based) in emit-only mode: it reads the request text from the prompt,
analyses the standard AL source checked out at the entry's base commit, and writes its `Final_Output`
decision (managed labels + advisory comment + open/closed state) to `triage_result.json` in the repo
root instead of applying it via `gh`. Like NL2AL and extensibility-request-implement, the category only
persists that raw decision; scoring is performed downstream by the LMChecklist judge against the entry's
`expected` checklist.
"""

import logging
from typing import Annotated, Literal, override

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

__all__ = ["DEFINITION", "TRIAGE_RESULT_FILE", "ExtRequestTriageCategory", "ExtRequestTriageEntry", "ManagedLabel"]

TRIAGE_RESULT_FILE = "triage_result.json"


type ManagedLabel = Literal[
    "Finance",
    "SCM",
    "Integration",
    "event-request",
    "request-for-external",
    "enum-request",
    "extensibility-enhancement",
    "missing-info",
    "agent-not-processable",
]


class ExtRequestTriageEntry(RepoGroundedEntry):
    """Dataset entry for the extensibility-request-triage category — triage a single extensibility request.

    Judge-based (no build, no tests), scored by LMChecklist like NL2AL and extensibility-request-implement.
    The agent reads one extensibility-request thread (rendered from `title` + `description` + any follow-up
    `comments`, plus `current_labels` already on the request) and analyses feasibility against the standard
    AL source checked out at `base_commit`. It writes its `Final_Output` triage decision — the managed labels
    to set, an advisory comment, and whether the request stays open or is closed. That raw decision is scored
    downstream by an LLM judge against `expected`, a checklist encoding the correct labels, issue state and the
    substance of the advisory comment.
    """

    # Triage has no gold code diff; the expected answer lives in the `expected` checklist below.
    patch: str | None = None

    title: Annotated[str, Field(min_length=1)]
    description: Annotated[str, Field(min_length=1)]
    comments: str = ""
    current_labels: Annotated[list[ManagedLabel], Field(default_factory=list)]

    # LLM-judge checklist: expected labels_to_set, issue_state and advisory-comment substance.
    expected: Annotated[list[ChecklistAssertion], Field(min_length=1)]

    @override
    def get_task(self) -> str:
        sections = [f"# {self.title}", "", self.description.rstrip()]
        if self.current_labels:
            sections += ["", f"Current labels: {', '.join(self.current_labels)}"]
        if self.comments.strip():
            sections += ["", "## Follow-up conversation", "", self.comments.rstrip()]
        return "\n".join(sections)

    @override
    def get_expected_output(self) -> Checklist:
        return {"assertions": self.expected}


class ExtRequestTriageCategory(Category[EvaluationContext[ExtRequestTriageEntry], JudgeBasedEvaluationResult]):
    """No BC container, no build, no tests."""

    @override
    def prepare_workspace(self, task: EvaluationContext[ExtRequestTriageEntry]) -> None:
        setup_repo_prebuild(task.entry, task.repo_path)
        (task.repo_path / TRIAGE_RESULT_FILE).unlink(missing_ok=True)

    @override
    def prepare(self, task: EvaluationContext[ExtRequestTriageEntry]) -> None:
        self.prepare_workspace(task)

    @override
    def grade(self, task: EvaluationContext[ExtRequestTriageEntry], result: AgentResult) -> JudgeBasedEvaluationResult:
        result_path = task.repo_path / TRIAGE_RESULT_FILE
        raw = result_path.read_text(encoding="utf-8").strip() if result_path.exists() else ""

        if not raw:
            logger.warning(f"Agent produced no {TRIAGE_RESULT_FILE} for {task.entry.instance_id}")
            return JudgeBasedEvaluationResult.create_empty_output(task, result)

        logger.info(f"Saved raw extensibility-request-triage result for {task.entry.instance_id} (scoring pending)")
        return JudgeBasedEvaluationResult.create_raw(task, result, output=raw)


DEFINITION: CategoryDefinition[ExtRequestTriageEntry] = CategoryDefinition(
    category=EvaluationCategory.EXT_REQUEST_TRIAGE,
    dataset_files={DatasetTier.GOLD: "extensibility_request_triage.jsonl"},
    entry_type=ExtRequestTriageEntry,
    result_type=JudgeBasedEvaluationResult,
    summary_type=JudgeBasedEvaluationResultSummary,
    aggregate_type=JudgeBasedLeaderboardAggregate,
    evaluators=("lm_checklist",),
    core_score="test_passed",
    judge="lm-checklist",
    runner="ubuntu-latest",
    requires_container=False,
    pass_bc_credentials=True,
    make=lambda _agent_config: ExtRequestTriageCategory(),
)
