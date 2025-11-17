"""Test-generation evaluation pipeline implementation."""

from collections.abc import Callable

from bcbench.evaluate.base import EvaluationPipeline
from bcbench.evaluate.evaluation_context import EvaluationContext
from bcbench.exceptions import (
    BuildError,
    BuildTimeoutExpired,
    PatchApplicationError,
    TestExecutionError,
    TestExecutionTimeoutExpired,
)
from bcbench.logger import get_logger, github_log_group
from bcbench.operations import (
    apply_patch,
    build_and_publish_projects,
    checkout_commit,
    clean_repo,
    get_generated_diff,
    run_tests,
)
from bcbench.results import EvaluationResult

logger = get_logger(__name__)

__all__ = ["TestGenerationPipeline"]


class TestGenerationPipeline(EvaluationPipeline):
    """Pipeline for test-generation evaluation category.

    Workflow:
    1. Setup: clean repo, checkout base commit, build
    2. Run agent: execute agent to generate test code
    3. Validate: apply generated tests, build, validate with reversed expectations

    Note: Full test generation logic is not yet implemented.
    Currently uses placeholder test_patch.
    """

    def setup(self, context: EvaluationContext) -> None:
        """Setup environment: clean repo, checkout, build."""
        clean_repo(context.repo_path)
        checkout_commit(context.repo_path, context.entry.base_commit)
        build_and_publish_projects(
            context.repo_path,
            context.entry.project_paths,
            context.container_name,
            context.username,
            context.password,
            context.entry.environment_setup_version,
        )

    def run_agent(self, context: EvaluationContext, agent_runner: Callable) -> None:
        """Run the agent and capture metrics."""
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.agent_metrics, context.mcp_servers, context.custom_instructions = agent_runner(context)

    def evaluate(self, context: EvaluationContext) -> None:
        """Apply generated tests, build, and validate with reversed expectations.

        TODO: Extract generated tests from agent output
        TODO: Validate tests fail on bad code, pass on good code

        Creates and saves appropriate result based on validation outcome.
        """
        generated_patch = get_generated_diff(context.repo_path)
        result = None

        try:
            # For test generation: apply generated tests instead of test_patch
            # TODO: Extract generated tests from agent output
            # TODO: Validate tests fail on bad code, pass on good code
            apply_patch(context.repo_path, context.entry.test_patch, f"{context.entry.instance_id} generated tests")
            build_and_publish_projects(
                context.repo_path,
                context.entry.project_paths,
                context.container_name,
                context.username,
                context.password,
                context.entry.environment_setup_version,
            )
            # TODO: Implement test validation with reversed expectation
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

        finally:
            if result is not None:
                self.save_result(context, result)
            else:
                logger.error(f"No result generated for {context.entry.instance_id}")
                raise RuntimeError(f"No result generated for {context.entry.instance_id}")
