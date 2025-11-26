from collections.abc import Callable

from bcbench.config import get_config
from bcbench.dataset import TestEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import BuildError, TestExecutionError
from bcbench.logger import get_logger, github_log_group
from bcbench.operations import (
    apply_patch,
    build_and_publish_projects,
    categorize_projects,
    checkout_commit,
    clean_project_paths,
    clean_repo,
    copy_problem_statement_folder,
    extract_tests_from_patch,
    stage_and_get_diff,
)
from bcbench.operations.bc_operations import run_test_suite
from bcbench.results.testgeneration import TestGenerationResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)
_config = get_config()

__all__ = ["TestGenerationPipeline"]


class TestGenerationPipeline(EvaluationPipeline):
    """Pipeline for test-generation evaluation category.

    Workflow:
    1. Setup: clean repo, checkout base commit, copy problem statement, build
    2. Run agent: execute agent to generate test code
    3. Evaluate: build, run tests with expected failures, then apply original patch, build, run tests with expected passes
    """

    def setup(self, context: EvaluationContext) -> None:
        clean_repo(context.repo_path)
        checkout_commit(context.repo_path, context.entry.base_commit)
        copy_problem_statement_folder(context.entry, context.repo_path)

        build_and_publish_projects(
            context.repo_path,
            context.entry.project_paths,
            context.container_name,
            context.username,
            context.password,
            context.entry.environment_setup_version,
        )

    def run_agent(self, context: EvaluationContext, agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext) -> None:
        test_projects, app_projects = categorize_projects(context.entry.project_paths)

        # Clean app projects to revert any unintended agent changes before capturing diff
        # Evaluation focuses on valid changes (test code), treating unintended modifications as out-of-scope noise
        clean_project_paths(context.repo_path, app_projects)

        generated_patch: str = stage_and_get_diff(context.repo_path)
        generated_tests: list[TestEntry] = extract_tests_from_patch(generated_patch, context.repo_path)
        result: TestGenerationResult | None = None

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

            result = TestGenerationResult.create_success(context, generated_patch, pre_patch_failed=True, post_patch_passed=True)
            logger.info(f"Successfully completed {context.entry.instance_id}")

        except BuildError as e:
            result = TestGenerationResult.create_build_failure(context, generated_patch, f"Build failed: {e.project_path}")
            logger.error(f"Build failed during evaluation of {context.entry.instance_id}: {e}")

        except TestExecutionError as e:
            if e.expectation == "Fail":
                result = TestGenerationResult.create_test_failure(context, generated_patch, "Generated tests Passed pre-patch", pre_patch_failed=False)
            else:
                result = TestGenerationResult.create_test_failure(context, generated_patch, "Generated tests Failed post-patch", pre_patch_failed=True, post_patch_passed=False)

            logger.error(f"Tests failed during evaluation of {context.entry.instance_id}: {e}")

        finally:
            if result is not None:
                self.save_result(context, result)
            else:
                logger.error(f"No result generated for {context.entry.instance_id}")
                raise RuntimeError(f"No result generated for {context.entry.instance_id}")
