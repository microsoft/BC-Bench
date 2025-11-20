"""Core evaluation pipeline for running agents against benchmark entries."""

from collections.abc import Callable

from bcbench.config import get_config
from bcbench.evaluate.evaluation_context import EvaluationContext
from bcbench.exceptions import BuildError, BuildTimeoutExpired, PatchApplicationError, TestExecutionError, TestExecutionTimeoutExpired
from bcbench.logger import get_logger, github_log_group
from bcbench.operations.bc_operations import build_and_publish_projects, run_tests
from bcbench.operations.git_operations import apply_patch, checkout_commit, clean_repo, get_generated_diff
from bcbench.results import EvaluationResult

logger = get_logger(__name__)
_config = get_config()
__all__ = ["run_extensibility_evaluation_pipeline"]


def run_extensibility_evaluation_pipeline(
    context: EvaluationContext,
    agent_runner: Callable[[EvaluationContext], tuple[dict[str, float | int] | None, list[str] | None, bool]],
) -> None:
    """Common evaluation pipeline for all agents.

    This function handles the complete evaluation workflow:
    1. Setup environment (clean repo, checkout, build)
    2. Run agent (agent-specific implementation)
    3. Apply test patch and validate
    4. Save results

    Args:
        context: Evaluation context containing all configuration
        agent_runner: Function that runs the specific agent and returns metrics dict or None
            Expected metrics keys: agent_execution_time, prompt_tokens, completion_tokens, etc
            Also returns a list of MCP server names or None, and a boolean for custom instructions
    """
    # Setup environment
    clean_repo(context.repo_path)
    if context.entry.base_commit:
        checkout_commit(context.repo_path, context.entry.base_commit)

    result = None

    # Run agent (agent-specific)
    with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
        context.agent_metrics, context.mcp_servers, context.custom_instructions = agent_runner(context)

    result = EvaluationResult.create_success(context, "")

    logger.info(f"Successfully completed {context.entry.instance_id}")

    if result is not None:
        result.save(context.result_dir, f"{context.entry.instance_id}{_config.file_patterns.result_pattern}")
    else:
        logger.error(f"No result generated for {context.entry.instance_id}")
        raise RuntimeError(f"No result generated for {context.entry.instance_id}")
