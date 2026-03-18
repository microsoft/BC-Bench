from collections.abc import Callable

from bcbench.dataset.dataset_entry import BugFixTestGenEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import BuildError, TestExecutionError
from bcbench.logger import get_logger, github_log_group
from bcbench.operations import (
    apply_patch,
    build_and_publish_projects,
    categorize_projects,
    clean_project_paths,
    run_tests,
    setup_repo_postbuild,
    setup_repo_prebuild,
    stage_and_get_diff,
)
from bcbench.results.bugfix import BugFixResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["BugFixPipeline"]


class BugFixPipeline(EvaluationPipeline):
    """Pipeline for bug-fix evaluation category."""

    def _get_entry(self, context: EvaluationContext) -> BugFixTestGenEntry:
        assert isinstance(context.entry, BugFixTestGenEntry)
        return context.entry

    def setup(self, context: EvaluationContext) -> None:
        entry = self._get_entry(context)

        setup_repo_prebuild(entry, context.repo_path)

        build_and_publish_projects(
            context.repo_path,
            entry.project_paths,
            context.container_name,
            context.username,
            context.password,
            entry.environment_setup_version,
        )

        setup_repo_postbuild(entry, context.repo_path, context.category)

    def run_agent(self, context: EvaluationContext, agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext) -> None:
        entry = self._get_entry(context)
        test_projects, _app_projects = categorize_projects(entry.project_paths)

        # Clean test projects to revert any unintended agent changes before capturing diff
        clean_project_paths(context.repo_path, test_projects)

        generated_patch = stage_and_get_diff(context.repo_path)
        result: BugFixResult | None = None

        try:
            apply_patch(context.repo_path, entry.test_patch, f"{entry.instance_id} test patch")
            build_and_publish_projects(
                context.repo_path,
                entry.project_paths,
                context.container_name,
                context.username,
                context.password,
                entry.environment_setup_version,
            )
            run_tests(entry, context.container_name, context.username, context.password)

            result = BugFixResult.create_success(context, generated_patch)
            logger.info(f"Successfully completed {entry.instance_id}")

        except BuildError as e:
            result = BugFixResult.create_build_failure(context, generated_patch, str(e))
            logger.error(f"Build failed during evaluation of {entry.instance_id}: {e}")

        except TestExecutionError as e:
            result = BugFixResult.create_test_failure(context, generated_patch, error_msg="Test failed\n" + str(e))
            logger.error(f"Tests failed during evaluation of {entry.instance_id}: {e}")

        finally:
            if result is not None:
                self.save_result(context, result)
            else:
                logger.error(f"No result generated for {entry.instance_id}")
                raise RuntimeError(f"No result generated for {entry.instance_id}")
