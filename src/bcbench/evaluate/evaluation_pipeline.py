"""Core evaluation pipeline for running agents against benchmark entries."""

from collections.abc import Callable

from bcbench.evaluate import EvaluationContext, EvaluationResult
from bcbench.exceptions import BuildError, PatchApplicationError, TestExecutionError
from bcbench.logger import get_logger, github_log_group
from bcbench.operations.bc_operations import build_and_publish_projects, run_tests
from bcbench.operations.git_operations import apply_patch, checkout_commit, clean_repo

logger = get_logger(__name__)

__all__ = ["run_evaluation_pipeline"]


def run_evaluation_pipeline(
    context: EvaluationContext,
    agent_runner: Callable[[EvaluationContext], None],
) -> None:
    """Common evaluation pipeline for all agents.

    This function handles the complete evaluation workflow:
    1. Setup environment (clean repo, checkout, build)
    2. Run agent (agent-specific implementation)
    3. Apply test patch and validate
    4. Save results

    Args:
        context: Evaluation context containing all configuration
        agent_runner: Function that runs the specific agent with the context
    """
    result = EvaluationResult(
        instance_id=context.entry.instance_id,
        version=context.entry.environment_setup_version,
    )

    try:
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

        # Run agent (agent-specific)
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            agent_runner(context)

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

        # TODO: Parse test_results to extract pass/fail counts and resolved status
        # For now, assume resolved if no exception (error will be thrown when tests fail)
        result.resolved = True
        logger.info(f"Successfully completed {context.entry.instance_id}")

    except PatchApplicationError as e:
        result.resolved = False
        result.error_message = f"Failed to apply {e.patch_name}"
        logger.error(f"Failed to apply test patch for {context.entry.instance_id}: {e}")

    except BuildError as e:
        result.resolved = False
        result.error_message = f"Build failed: {e.project_path}"
        logger.error(f"Build failed during evaluation of {context.entry.instance_id}: {e}")

    except TestExecutionError as e:
        result.resolved = False
        result.error_message = "Tests failed"
        logger.error(f"Tests failed during evaluation of {context.entry.instance_id}: {e}")

    except Exception as e:
        result.resolved = False
        result.error_message = f"Unexpected error: {e}"
        logger.error(f"Failed to process {context.entry.instance_id}: {e}")

    finally:
        result.save(context.result_dir, f"instance_results_{context.entry.instance_id}.jsonl")
