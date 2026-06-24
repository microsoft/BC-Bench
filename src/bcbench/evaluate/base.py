from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.results import BaseEvaluationResult
from bcbench.types import AgentMetrics, EvaluationContext, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()

__all__ = ["EvaluationPipeline"]


class EvaluationPipeline[E: BaseDatasetEntry](ABC):
    """Abstract base class for evaluation pipelines.

    Subclasses implement category-specific setup, agent execution, and validation logic.
    The execute() method provides a template orchestrating the overall evaluation flow.
    """

    @abstractmethod
    def setup_workspace(self, entry: E, repo_path: Path) -> None:
        """Prepare the workspace for agent execution (no build).

        Used by the `run` command to set up the repo without building.
        """
        raise NotImplementedError()

    @abstractmethod
    def setup(self, context: EvaluationContext[E]) -> None:
        """Setup environment: e.g. clean repo, checkout base commit, initial build.

        Args:
            context: Evaluation context with configuration

        Raises:
            Exception: If setup fails (build, checkout, etc.)
        """
        raise NotImplementedError()

    @abstractmethod
    def run_agent(self, context: EvaluationContext[E], agent_runner: Callable) -> None:
        """Run the agent and capture metrics.

        Args:
            context: Evaluation context with configuration
            agent_runner: Function that runs the specific agent

        Raises:
            Exception: If agent execution fails
        """
        raise NotImplementedError()

    @abstractmethod
    def evaluate(self, context: EvaluationContext[E]) -> None:
        """Evaluate results: e.g. apply patches, build, run tests.

        Implementation should raise category-specific exceptions on failure.

        Args:
            context: Evaluation context with configuration

        Raises:
            Exception: If evaluation fails (patch application, build, tests)
        """
        raise NotImplementedError()

    def execute(
        self,
        context: EvaluationContext[E],
        agent_runner: Callable[[EvaluationContext[E]], tuple[AgentMetrics | None, ExperimentConfiguration | None]],
    ) -> None:
        """Template method orchestrating the evaluation flow.

        Executes setup, runs agent, evaluates results, and saves outcomes.
        Result creation and error handling is now done explicitly within evaluate().

        Args:
            context: Evaluation context with configuration
            agent_runner: Function that runs the specific agent and returns (AgentMetrics, ExperimentConfiguration)
        """
        self.setup(context)

        try:
            self.run_agent(context, agent_runner)
        except AgentTimeoutError as e:
            context.metrics = e.metrics
            context.experiment = e.config
            result = BaseEvaluationResult.create_agent_timeout_failure(context)
            self.save_result(context, result)
            logger.info("Agent timed out during execution, counting as failure.")
            return
        finally:
            logger.info(f"Agent metrics: {context.metrics}")
            logger.info(f"Experiment configuration: {context.experiment}")

        self.evaluate(context)

    def save_result(self, context: EvaluationContext[E], result: BaseEvaluationResult) -> None:
        """Save result directly using result object.

        Args:
            context: Evaluation context with configuration
            result: BaseEvaluationResult to save
        """

        result.save(context.result_dir, f"{context.entry.instance_id}{_config.file_patterns.result_pattern}")
