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
__all__ = ["run_evaluation_pipeline"]


def run_evaluation_pipeline(
    context: EvaluationContext,
    agent_runner: Callable[[EvaluationContext], tuple[dict[str, float | int] | None, list[str] | None]],
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
            Also returns a list of MCP server names or None
    """
    # Setup environment
    clean_repo(context.repo_path)
    checkout_commit(context.repo_path, context.entry.base_commit)

    # Initial build, ensure symbols, etc. align with base commit
    build_and_publish_projects(
        context.repo_path,
        context.entry.project_paths,
        context.container_name,
        context.username,
        context.password,
        context.entry.environment_setup_version,
    )

    result = None

    # Run agent (agent-specific)
    with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
        context.agent_metrics, context.mcp_servers = agent_runner(context)

    generated_patch: str = get_generated_diff(context.repo_path)

    try:
        # Apply test patch and validate
        apply_patch(context.repo_path, context.entry.test_patch, f"{context.entry.instance_id} test patch")
        build_and_publish_projects(
            context.repo_path,
            context.entry.project_paths,
            context.container_name,
            context.username,
            context.password,
            context.entry.environment_setup_version,
        )
        run_tests(context.entry, context.container_name, context.username, context.password)

        result = EvaluationResult.create_success(context, generated_patch)
        logger.info(f"Successfully completed {context.entry.instance_id}")

    except PatchApplicationError as e:
        result = EvaluationResult.create_build_failure(context, generated_patch, f"Failed to apply {e.patch_name}")
        logger.error(f"Failed to apply test patch for {context.entry.instance_id}: {e}")

    except BuildError as e:
        result = EvaluationResult.create_build_failure(context, generated_patch, f"Build failed: {e.project_path}")
        logger.error(f"Build failed during evaluation of {context.entry.instance_id}: {e}")

    except BuildTimeoutExpired as e:
        result = EvaluationResult.create_build_failure(context, generated_patch, f"Build timed out: {e.project_path}")
        logger.error(f"Build timed out during evaluation of {context.entry.instance_id}: {e}")

    except TestExecutionError as e:
        result = EvaluationResult.create_test_failure(context, generated_patch)
        logger.error(f"Tests failed during evaluation of {context.entry.instance_id}: {e}")

    except TestExecutionTimeoutExpired as e:
        result = EvaluationResult.create_test_failure(context, generated_patch, "Tests timed out")
        logger.error(f"Tests timed out during evaluation of {context.entry.instance_id}: {e}")

    except Exception as e:
        logger.error(f"Unexpected error during evaluation of {context.entry.instance_id}: {e}")
        raise

    finally:
        if result is not None:
            result.save(context.result_dir, f"{context.entry.instance_id}{_config.file_patterns.result_pattern}")
        else:
            logger.error(f"No result generated for {context.entry.instance_id}")
            raise RuntimeError(f"No result generated for {context.entry.instance_id}")
