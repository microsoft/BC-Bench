from collections.abc import Callable

from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import BuildError, TestExecutionError
from bcbench.logger import get_logger, github_log_group
from bcbench.operations import (
    apply_patch,
    build_and_publish_projects,
    categorize_projects,
    clean_project_paths,
    run_tests,
    setup_repo,
    stage_and_get_diff,
)
from bcbench.results.bugfix import BugFixResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["BugFixPipeline"]


class BugFixPipeline(EvaluationPipeline):
    """Pipeline for bug-fix evaluation category.

    Workflow:
    1. Setup: clean repo, checkout base commit, copy problem statement, build
    2. Run agent: execute agent to generate fix patch
    3. evaluate: apply test patch, build, run tests
    """

    def setup(self, context: EvaluationContext) -> None:
        setup_repo(context.entry, context.repo_path, context.category)

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
        """Apply test patch, build, and run tests.

        Creates and saves appropriate result based on validation outcome.
        """
        test_projects, _app_projects = categorize_projects(context.entry.project_paths)

        # Clean test projects to revert any unintended agent changes before capturing diff
        # Evaluation focuses on valid changes (app code), treating unintended modifications as out-of-scope noise
        clean_project_paths(context.repo_path, test_projects)

        generated_patch = stage_and_get_diff(context.repo_path)
        result: BugFixResult | None = None

        try:
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

            result = BugFixResult.create_success(context, generated_patch)
            logger.info(f"Successfully completed {context.entry.instance_id}")

        except BuildError as e:
            result = BugFixResult.create_build_failure(context, generated_patch, f"Build failed: {e.project_path}")
            logger.error(f"Build failed during evaluation of {context.entry.instance_id}: {e}")

        except TestExecutionError as e:
            result = BugFixResult.create_test_failure(context, generated_patch)
            logger.error(f"Tests failed during evaluation of {context.entry.instance_id}: {e}")

        finally:
            if result is not None:
                self.save_result(context, result)
            else:
                logger.error(f"No result generated for {context.entry.instance_id}")
                raise RuntimeError(f"No result generated for {context.entry.instance_id}")
