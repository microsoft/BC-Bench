from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

from bcbench_core.evaluation import AgentRunner as CoreAgentRunner
from bcbench_core.evaluation import EvaluationPipeline as CoreEvaluationPipeline

from bcbench.dataset.dataset_entry import BaseDatasetEntry
from bcbench.exceptions import AgentTimeoutError
from bcbench.results.base import BaseEvaluationResult
from bcbench.types import AgentMetrics, EvaluationContext, ExperimentConfiguration

logger = logging.getLogger(__name__)

__all__ = ["AgentRunner", "EvaluationPipeline", "LogGroup"]

type AgentRunner[E: BaseDatasetEntry] = CoreAgentRunner[EvaluationContext[E], AgentMetrics, ExperimentConfiguration]
type LogGroup = Callable[[str], AbstractContextManager[None]]


class EvaluationPipeline[E: BaseDatasetEntry](CoreEvaluationPipeline[EvaluationContext[E], AgentMetrics, ExperimentConfiguration, BaseEvaluationResult]):
    def __init__(self, *, result_class: type[BaseEvaluationResult], result_suffix: str, log_group: LogGroup | None = None) -> None:
        self._result_class = result_class
        self._result_suffix = result_suffix
        self._log_group = log_group

    def log_group(self, title: str) -> AbstractContextManager[None]:
        return self._log_group(title) if self._log_group is not None else nullcontext()

    @abstractmethod
    def setup_workspace(self, entry: E, repo_path: Path) -> None:
        """Prepare the workspace for the run command without building."""
        raise NotImplementedError

    def result_path(self, context: EvaluationContext[E], result: BaseEvaluationResult) -> Path:
        return context.result_dir / f"{context.entry.instance_id}{self._result_suffix}"

    def handle_agent_timeout(self, context: EvaluationContext[E], error: TimeoutError) -> None:
        if not isinstance(error, AgentTimeoutError):
            raise error
        context.metrics = error.metrics
        context.experiment = error.config
        result = self._result_class.create_agent_timeout_failure(context)
        self.save_result(context, result)
        logger.info("Agent timed out during execution, counting as failure.")

    def after_agent(self, context: EvaluationContext[E]) -> None:
        logger.info(f"Agent metrics: {context.metrics}")
        logger.info(f"Experiment configuration: {context.experiment}")
