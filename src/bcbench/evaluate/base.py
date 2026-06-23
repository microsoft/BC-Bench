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

    def max_agent_attempts(self) -> int:
        """Total number of agent attempts (including the first).

        Defaults to 1 (no retry). Pipelines whose agents suffer from transient failures (e.g. a hard
        wall-clock timeout) can override this to retry. Kept as a method so subclasses can source the
        value from configuration.
        """
        return 1

    def agent_produced_output(self, context: EvaluationContext[E]) -> bool:
        """Return whether the agent produced any usable output on the last attempt.

        Used by ``execute()`` to decide whether an empty (no-change) run is worth retrying. Defaults
        to ``True`` so pipelines that do not distinguish empty output are never retried on this basis.
        """
        return True

    def execute(
        self,
        context: EvaluationContext[E],
        agent_runner: Callable[[EvaluationContext[E]], tuple[AgentMetrics | None, ExperimentConfiguration | None]],
    ) -> None:
        """Template method orchestrating the evaluation flow.

        Executes setup, runs agent, evaluates results, and saves outcomes.
        Result creation and error handling is now done explicitly within evaluate().

        The agent step is retried up to ``max_agent_attempts()`` times, but only on transient
        outcomes — an agent timeout or empty output. Each retry re-runs ``setup()`` for a clean
        workspace. The final attempt's outcome is the one that is evaluated/persisted.

        Args:
            context: Evaluation context with configuration
            agent_runner: Function that runs the specific agent and returns (AgentMetrics, ExperimentConfiguration)
        """
        max_attempts = self.max_agent_attempts()

        for attempt in range(1, max_attempts + 1):
            is_last_attempt = attempt == max_attempts
            self.setup(context)

            try:
                self.run_agent(context, agent_runner)
            except AgentTimeoutError as e:
                if not is_last_attempt:
                    logger.warning(f"Agent timed out for {context.entry.instance_id} (attempt {attempt}/{max_attempts}); retrying.")
                    continue
                context.metrics = e.metrics
                context.experiment = e.config
                logger.info(f"Agent metrics: {context.metrics}")
                logger.info(f"Experiment configuration: {context.experiment}")
                result = BaseEvaluationResult.create_agent_timeout_failure(context)
                self.save_result(context, result)
                logger.info("Agent timed out during execution, counting as failure.")
                return

            logger.info(f"Agent metrics: {context.metrics}")
            logger.info(f"Experiment configuration: {context.experiment}")

            if not is_last_attempt and not self.agent_produced_output(context):
                logger.warning(f"Agent produced no output for {context.entry.instance_id} (attempt {attempt}/{max_attempts}); retrying.")
                continue

            break

        self.evaluate(context)

    def save_result(self, context: EvaluationContext[E], result: BaseEvaluationResult) -> None:
        """Save result directly using result object.

        Args:
            context: Evaluation context with configuration
            result: BaseEvaluationResult to save
        """

        result.save(context.result_dir, f"{context.entry.instance_id}{_config.file_patterns.result_pattern}")
