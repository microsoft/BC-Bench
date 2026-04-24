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
        """Produce the per-instance result from the post-agent workspace.

        The work done here depends on the category's scoring style:

        - Execution-based categories (e.g. bug-fix, test-generation) perform real
          verification in-process — applying patches, building, running tests —
          and derive a deterministic ground-truth outcome (resolved/build)
          that is stored on the result. bc-eval evaluators for these
          categories are thin pass-throughs over that metadata.
        - LLM-as-judge categories (e.g. checklist-scored reviews) do no scoring
          here. They simply capture the agent's artifact (e.g. the review
          text) on the result. Scoring is deferred to bc-eval, where an LLM
          judge evaluates the artifact against per-instance assertions. This
          keeps `bcbench run` offline-capable, cheap to iterate, and lets
          scores be re-derived when the judge model or assertions evolve.

        Implementations are responsible for constructing the appropriate
        BaseEvaluationResult and calling self.save_result. Category-specific
        exceptions should be raised on failure.

        Args:
            context: Evaluation context with configuration

        Raises:
            Exception: If in-pipeline verification fails (patch application,
                build, tests) for execution-based categories.
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
