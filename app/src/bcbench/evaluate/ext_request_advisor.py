from pathlib import Path

from bcbench.dataset import ExtRequestAdvisorEntry
from bcbench.evaluate.base import AgentRunner, EvaluationPipeline
from bcbench.github_actions import github_log_group
from bcbench.logger import get_logger
from bcbench.operations import setup_repo_prebuild
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["ADVISOR_RESULT_FILE", "ExtRequestAdvisorPipeline"]

ADVISOR_RESULT_FILE = "advisor_result.json"


class ExtRequestAdvisorPipeline(EvaluationPipeline[ExtRequestAdvisorEntry]):
    """Offline single-shot proxy for the interactive extensibility advisor."""

    def setup_workspace(self, entry: ExtRequestAdvisorEntry, repo_path: Path) -> None:
        setup_repo_prebuild(entry, repo_path)
        (repo_path / ADVISOR_RESULT_FILE).unlink(missing_ok=True)

    def setup(self, context: EvaluationContext[ExtRequestAdvisorEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext[ExtRequestAdvisorEntry], agent_runner: AgentRunner[ExtRequestAdvisorEntry]) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[ExtRequestAdvisorEntry]) -> None:
        result_path = context.repo_path / ADVISOR_RESULT_FILE
        raw = result_path.read_text(encoding="utf-8").strip() if result_path.exists() else ""

        if not raw:
            result = JudgeBasedEvaluationResult.create_empty_output(context)
            logger.warning(f"Agent produced no {ADVISOR_RESULT_FILE} for {context.entry.instance_id}")
        else:
            result = JudgeBasedEvaluationResult.create_raw(context, output=raw)
            logger.info(f"Saved raw extensibility-request-advisor result for {context.entry.instance_id} (scoring pending)")

        self.save_result(context, result)
