"""Core evaluation pipeline for running agents against benchmark entries."""

from collections.abc import Callable

from bcbench.evaluate.evaluation_context import EvaluationContext
from bcbench.evaluate.evaluation_result import EvaluationResult
from bcbench.exceptions import BuildError, PatchApplicationError, TestExecutionError
from bcbench.logger import get_logger, github_log_group
from bcbench.operations.bc_operations import build_and_publish_projects, run_tests
from bcbench.operations.git_operations import apply_patch, checkout_commit, clean_repo, save_git_diff

logger = get_logger(__name__)

__all__ = ["run_evaluation_pipeline"]


def run_evaluation_pipeline(
    context: EvaluationContext,
    agent_runner: Callable[[EvaluationContext], dict[str, float | int] | None],
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
    """
    result = None

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
            agent_metrics = agent_runner(context)
            context.agent_metrics = agent_metrics

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

        result = _create_success_result(context)
        logger.info(f"Successfully completed {context.entry.instance_id}")

    except PatchApplicationError as e:
        result = _create_build_failure_result(context, f"Failed to apply {e.patch_name}")
        logger.error(f"Failed to apply test patch for {context.entry.instance_id}: {e}")

    except BuildError as e:
        result = _create_build_failure_result(context, f"Build failed: {e.project_path}")
        logger.error(f"Build failed during evaluation of {context.entry.instance_id}: {e}")

    except TestExecutionError as e:
        result = _create_test_failure_result(context)
        logger.error(f"Tests failed during evaluation of {context.entry.instance_id}: {e}")

    except Exception as e:
        result = _create_unexpected_error_result(context, e)
        logger.error(f"Failed to process {context.entry.instance_id}: {e}")

    finally:
        if result is not None:
            result.save(context.result_dir, f"instance_results_{context.entry.instance_id}.jsonl")
            save_git_diff(context.result_dir, context.repo_path)
        else:
            logger.error(f"No result generated for {context.entry.instance_id}")
            raise RuntimeError(f"No result generated for {context.entry.instance_id}")


def _create_result(context: EvaluationContext, resolved: bool, build: bool, error_message: str | None = None) -> EvaluationResult:
    metrics = context.agent_metrics or {}
    prompt_tokens = metrics.get("prompt_tokens")
    completion_tokens = metrics.get("completion_tokens")
    return EvaluationResult(
        instance_id=context.entry.instance_id,
        version=context.entry.environment_setup_version,
        resolved=resolved,
        build=build,
        model=context.model,
        agent_name=context.agent_name,
        error_message=error_message,
        agent_execution_time=metrics.get("agent_execution_time"),
        prompt_tokens=int(prompt_tokens) if prompt_tokens is not None else None,
        completion_tokens=int(completion_tokens) if completion_tokens is not None else None,
    )


def _create_success_result(context: EvaluationContext) -> EvaluationResult:
    return _create_result(context, resolved=True, build=True)


def _create_build_failure_result(context: EvaluationContext, error_msg: str) -> EvaluationResult:
    return _create_result(context, resolved=False, build=False, error_message=error_msg)


def _create_test_failure_result(context: EvaluationContext) -> EvaluationResult:
    return _create_result(context, resolved=False, build=True, error_message="Tests failed")


def _create_unexpected_error_result(context: EvaluationContext, error: Exception) -> EvaluationResult:
    return _create_result(context, resolved=False, build=False, error_message=f"Unexpected error: {error}")
