from collections.abc import Callable

from bcbench.dataset import TestEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import BuildError, TestExecutionError
from bcbench.logger import get_logger, github_log_group
from bcbench.operations import apply_patch, build_and_publish_projects, checkout_commit, clean_repo, extract_tests_from_patch, get_generated_diff
from bcbench.operations.bc_operations import run_test_suite
from bcbench.operations.instruction_operations import setup_custom_agent
from bcbench.results import EvaluationResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["TestGenerationPipeline"]


class TestGenerationPipeline(EvaluationPipeline):
    """Pipeline for test-generation evaluation category.

    Workflow:
    1. Setup: clean repo, checkout base commit, build
    2. Run agent: execute agent to generate test code
    3. Evaluate: build, run tests with expected failures, then apply original patch, build, run tests with expected passes
    """

    def setup(self, context: EvaluationContext) -> None:
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
        setup_custom_agent(context.repo_path, context.entry.repo, context.agent_dir)


    def run_agent(self, context: EvaluationContext, agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.agent_metrics, context.mcp_servers, context.custom_instructions = agent_runner(context)

    def evaluate(self, context: EvaluationContext) -> None:
        generated_patch: str = get_generated_diff(context.repo_path)
        generated_tests: list[TestEntry] = extract_tests_from_patch(generated_patch, context.repo_path)
        result: EvaluationResult | None = None

        test_projects: list[str] = [project for project in context.entry.project_paths if "test" in project.lower()]
        app_projects: list[str] = [project for project in context.entry.project_paths if project not in test_projects]

        try:
            build_and_publish_projects(
                context.repo_path,
                test_projects,
                context.container_name,
                context.username,
                context.password,
                context.entry.environment_setup_version,
            )
            run_test_suite(generated_tests, "Fail", context.container_name, context.username, context.password)

            apply_patch(context.repo_path, context.entry.patch, f"{context.entry.instance_id} patch")

            build_and_publish_projects(
                context.repo_path,
                app_projects,
                context.container_name,
                context.username,
                context.password,
                context.entry.environment_setup_version,
            )
            run_test_suite(generated_tests, "Pass", context.container_name, context.username, context.password)

            result = EvaluationResult.create_success(context, generated_patch)
            logger.info(f"Successfully completed {context.entry.instance_id}")

        except BuildError as e:
            result = EvaluationResult.create_build_failure(context, generated_patch, f"Build failed: {e.project_path}")
            logger.error(f"Build failed during evaluation of {context.entry.instance_id}: {e}")

        except TestExecutionError as e:
            result = EvaluationResult.create_test_failure(context, generated_patch, error_msg=str(e))
            logger.error(f"Tests failed during evaluation of {context.entry.instance_id}: {e}")

        finally:
            if result is not None:
                self.save_result(context, result)
            else:
                logger.error(f"No result generated for {context.entry.instance_id}")
                raise RuntimeError(f"No result generated for {context.entry.instance_id}")
