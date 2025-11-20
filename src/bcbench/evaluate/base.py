from abc import ABC, abstractmethod
from collections.abc import Callable

from bcbench.logger import get_logger
from bcbench.results import BaseEvaluationResult
from bcbench.types import EvaluationCategory, EvaluationContext

logger = get_logger(__name__)

__all__ = ["EvaluationPipeline", "create_pipeline"]


class EvaluationPipeline(ABC):
    """Abstract base class for evaluation pipelines.

    Subclasses implement category-specific setup, agent execution, and validation logic.
    The execute() method provides a template orchestrating the overall evaluation flow.
    """

    @abstractmethod
    def setup(self, context: EvaluationContext) -> None:
        """Setup environment: e.g. clean repo, checkout base commit, initial build.

        Args:
            context: Evaluation context with configuration

        Raises:
            Exception: If setup fails (build, checkout, etc.)
        """
        raise NotImplementedError()

    @abstractmethod
    def run_agent(self, context: EvaluationContext, agent_runner: Callable) -> None:
        """Run the agent and capture metrics.

        Args:
            context: Evaluation context with configuration
            agent_runner: Function that runs the specific agent

        Raises:
            Exception: If agent execution fails
        """
        raise NotImplementedError()

    @abstractmethod
    def evaluate(self, context: EvaluationContext) -> None:
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
        context: EvaluationContext,
        agent_runner: Callable[[EvaluationContext], tuple[dict[str, float | int] | None, list[str] | None, bool]],
    ) -> None:
        """Template method orchestrating the evaluation flow.

        Executes setup, runs agent, evaluates results, and saves outcomes.
        Result creation and error handling is now done explicitly within evaluate().

        Args:
            context: Evaluation context with configuration
            agent_runner: Function that runs the specific agent and returns (metrics, mcp_servers, custom_instructions)
        """
        self.setup(context)
        self.run_agent(context, agent_runner)
        self.evaluate(context)

    def save_result(self, context: EvaluationContext, result: BaseEvaluationResult) -> None:
        """Save result directly using result object.

        Args:
            context: Evaluation context with configuration
            result: BaseEvaluationResult to save
        """
        from bcbench.config import get_config

        _config = get_config()
        result.save(context.result_dir, f"{context.entry.instance_id}{_config.file_patterns.result_pattern}")


def create_pipeline(category: EvaluationCategory) -> EvaluationPipeline:
    """Factory function to create evaluation pipeline based on category."""
    from bcbench.evaluate.bugfix import BugFixPipeline
    from bcbench.evaluate.testgeneration import TestGenerationPipeline

    match category:
        case EvaluationCategory.BUG_FIX:
            logger.info(f"Using BugFixPipeline for category: {category}")
            return BugFixPipeline()
        case EvaluationCategory.TEST_GENERATION:
            logger.info(f"Using TestGenerationPipeline for category: {category}")
            return TestGenerationPipeline()
        case _:
            raise ValueError(f"Unknown evaluation category: {category}")
    raise RuntimeError("Unreachable: no pipeline returned")
