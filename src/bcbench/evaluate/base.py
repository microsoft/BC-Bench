from __future__ import annotations

from abc import abstractmethod
from pathlib import Path

from bcbench_core.evaluation import AgentRunner as CoreAgentRunner
from bcbench_core.evaluation import EvaluationPipeline as CoreEvaluationPipeline

from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.results import BaseEvaluationResult
from bcbench.types import AgentMetrics, EvaluationContext, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()

__all__ = ["AgentRunner", "EvaluationPipeline"]

type AgentRunner[E: BaseDatasetEntry] = CoreAgentRunner[EvaluationContext[E], AgentMetrics, ExperimentConfiguration]


class EvaluationPipeline[E: BaseDatasetEntry](CoreEvaluationPipeline[EvaluationContext[E], AgentMetrics, ExperimentConfiguration, BaseEvaluationResult]):
    @abstractmethod
    def setup_workspace(self, entry: E, repo_path: Path) -> None:
        """Prepare the workspace for the run command without building."""
        raise NotImplementedError

    def result_path(self, context: EvaluationContext[E], result: BaseEvaluationResult) -> Path:
        return context.result_dir / f"{context.entry.instance_id}{_config.file_patterns.result_pattern}"

    def handle_agent_timeout(self, context: EvaluationContext[E], error: TimeoutError) -> None:
        if not isinstance(error, AgentTimeoutError):
            raise error
        context.metrics = error.metrics
        context.experiment = error.config
        result = context.category.result_class.create_agent_timeout_failure(context)
        self.save_result(context, result)
        logger.info("Agent timed out during execution, counting as failure.")

    def after_agent(self, context: EvaluationContext[E]) -> None:
        logger.info(f"Agent metrics: {context.metrics}")
        logger.info(f"Experiment configuration: {context.experiment}")
