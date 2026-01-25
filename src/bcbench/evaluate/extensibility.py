from collections.abc import Callable

from bcbench.config import get_config
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.logger import get_logger, github_log_group
from bcbench.operations.setup_operations import setup_repo_prebuild
from bcbench.results.extensibility import ExtensibilityResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)
_config = get_config()

__all__ = ["ExtensibilityPipeline"]


class ExtensibilityPipeline(EvaluationPipeline):
    def setup(self, context: EvaluationContext) -> None:
        setup_repo_prebuild(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext, agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext) -> None:
        result = ExtensibilityResult.create_success(context, "")

        logger.info(f"Successfully completed {context.entry.instance_id}")

        if result is not None:
            result.save(context.result_dir, f"{context.entry.instance_id}{_config.file_patterns.result_pattern}")
        else:
            logger.error(f"No result generated for {context.entry.instance_id}")
            raise RuntimeError(f"No result generated for {context.entry.instance_id}")
