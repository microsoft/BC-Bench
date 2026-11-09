from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from bcbench_core.agent.harness import AgentHarness, AgentResult
from bcbench_core.exceptions import AgentError, AgentTimeoutError

from bcbench.dataset import BaseDatasetEntry
from bcbench.github_actions import github_log_group
from bcbench.results import BaseEvaluationResult
from bcbench.results.base import RESULT_FILE_SUFFIX
from bcbench.types import EvaluationContext, HarnessName

logger = logging.getLogger(__name__)

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
        raise NotImplementedError

    @abstractmethod
    def setup(self, context: EvaluationContext[E]) -> None:
        """Setup environment: e.g. clean repo, checkout base commit, initial build.

        Args:
            context: Evaluation context with configuration

        Raises:
            Exception: If setup fails (build, checkout, etc.)
        """
        raise NotImplementedError

    def run_agent(self, context: EvaluationContext[E], harness: AgentHarness[E, HarnessName]) -> AgentResult:
        with github_log_group(f"{context.agent.harness} -- Entry: {context.entry.instance_id}"):
            return harness.run(context.agent_request())

    @abstractmethod
    def evaluate(self, context: EvaluationContext[E]) -> None:
        """Evaluate results: e.g. apply patches, build, run tests.

        Implementation should raise category-specific exceptions on failure.

        Args:
            context: Evaluation context with configuration

        Raises:
            Exception: If evaluation fails (patch application, build, tests)
        """
        raise NotImplementedError

    def execute(
        self,
        context: EvaluationContext[E],
        harness: AgentHarness[E, HarnessName],
    ) -> None:
        """Template method orchestrating the evaluation flow.

        Executes setup, runs agent, evaluates results, and saves outcomes.
        Result creation and error handling is now done explicitly within evaluate().

        Args:
            context: Evaluation context with configuration
            harness: The agent harness to run
        """
        self.setup(context)

        try:
            context.agent_result = self.run_agent(context, harness)
        except AgentTimeoutError as e:
            context.agent_result = AgentResult(metrics=e.metrics, experiment=e.config, transcript=e.transcript)
            result = context.category.result_class.create_agent_timeout_failure(context)
            self.save_result(context, result)
            logger.info("Agent timed out during execution, counting as failure.")
            return
        except AgentError as e:
            context.agent_result = AgentResult(transcript=e.transcript)
            raise
        finally:
            logger.info(f"Agent metrics: {context.agent_result.metrics}")
            logger.info(f"Experiment configuration: {context.agent_result.experiment}")

        self.evaluate(context)

    def save_result(self, context: EvaluationContext[E], result: BaseEvaluationResult) -> None:
        """Save result directly using result object.

        Args:
            context: Evaluation context with configuration
            result: BaseEvaluationResult to save
        """

        result.save(context.result_dir, f"{context.entry.instance_id}{RESULT_FILE_SUFFIX}")
