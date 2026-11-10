import logging
from pathlib import Path
from typing import override

from bcbench_core.agent.harness import AgentResult

from bcbench.dataset import ExtRequestAdvisorEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.operations import setup_repo_prebuild
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.types import EvaluationContext

logger = logging.getLogger(__name__)

__all__ = ["ADVISOR_RESULT_FILE", "ExtRequestAdvisorPipeline"]

ADVISOR_RESULT_FILE = "advisor_result.json"


class ExtRequestAdvisorPipeline(EvaluationPipeline[ExtRequestAdvisorEntry]):
    """Offline single-shot proxy for the interactive extensibility advisor."""

    @override
    def setup_workspace(self, entry: ExtRequestAdvisorEntry, repo_path: Path) -> None:
        setup_repo_prebuild(entry, repo_path)
        (repo_path / ADVISOR_RESULT_FILE).unlink(missing_ok=True)

    @override
    def setup(self, context: EvaluationContext[ExtRequestAdvisorEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    @override
    def evaluate(self, context: EvaluationContext[ExtRequestAdvisorEntry], agent_result: AgentResult) -> None:
        result_path = context.repo_path / ADVISOR_RESULT_FILE
        raw = result_path.read_text(encoding="utf-8").strip() if result_path.exists() else ""

        if not raw:
            result = JudgeBasedEvaluationResult.create_empty_output(context, agent_result)
            logger.warning(f"Agent produced no {ADVISOR_RESULT_FILE} for {context.entry.instance_id}")
        else:
            result = JudgeBasedEvaluationResult.create_raw(context, agent_result, output=raw)
            logger.info(f"Saved raw extensibility-request-advisor result for {context.entry.instance_id} (scoring pending)")

        self.save_result(context, result)
