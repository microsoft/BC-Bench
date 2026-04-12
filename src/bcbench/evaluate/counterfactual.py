import re
from collections.abc import Callable

from bcbench.dataset import BugFixEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import BuildError, PatchApplicationError, TestExecutionError
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
from bcbench.results.counterfactual import CounterfactualResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["CounterfactualPipeline"]

_CF_SUFFIX_PATTERN = re.compile(r"^(.+)__cf-\d+$")


class CounterfactualPipeline(EvaluationPipeline[BugFixEntry]):
    """Pipeline for counterfactual evaluation category.

    Workflow is identical to BugFixPipeline:
    1. Setup: clean repo, checkout base commit, copy problem statement, build
    2. Run agent: execute agent to generate fix patch
    3. Evaluate: apply counterfactual test patch, build, run tests

    The key difference is that the counterfactual entry's test_patch and FAIL_TO_PASS
    are used during evaluation instead of the base entry's.
    """

    def setup(self, context: EvaluationContext[BugFixEntry]) -> None:
        setup_repo_prebuild(context.entry, context.repo_path)

        build_and_publish_projects(
            context.repo_path,
            context.entry.project_paths,
            context.get_container(),
            context.entry.environment_setup_version,
        )

        setup_repo_postbuild(context.entry, context.repo_path, context.category)

    def run_agent(self, context: EvaluationContext[BugFixEntry], agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[BugFixEntry]) -> None:
        """Apply counterfactual test patch, build, and run tests."""
        container = context.get_container()
        test_projects, _app_projects = categorize_projects(context.entry.project_paths)

        clean_project_paths(context.repo_path, test_projects)

        generated_patch = stage_and_get_diff(context.repo_path)
        result: CounterfactualResult | None = None

        match = _CF_SUFFIX_PATTERN.match(context.entry.instance_id)
        base_instance_id = match.group(1) if match else ""

        try:
            apply_patch(context.repo_path, context.entry.test_patch, f"{context.entry.instance_id} test patch")
            build_and_publish_projects(
                context.repo_path,
                context.entry.project_paths,
                container,
                context.entry.environment_setup_version,
            )
            run_tests(context.entry, container)

            result = CounterfactualResult.create_success(context, generated_patch, base_instance_id=base_instance_id)
            logger.info(f"Successfully completed {context.entry.instance_id}")

        except BuildError as e:
            result = CounterfactualResult.create_build_failure(context, generated_patch, str(e), base_instance_id=base_instance_id)
            logger.error(f"Build failed during evaluation of {context.entry.instance_id}: {e}")

        except TestExecutionError as e:
            result = CounterfactualResult.create_test_failure(context, generated_patch, error_msg="Test failed\n" + str(e), base_instance_id=base_instance_id)
            logger.error(f"Tests failed during evaluation of {context.entry.instance_id}: {e}")

        except PatchApplicationError as e:
            result = CounterfactualResult.create_build_failure(context, generated_patch, f"Test patch application failed: {e}", base_instance_id=base_instance_id)
            logger.error(f"Test patch application failed for {context.entry.instance_id}: {e}")

        except Exception as e:
            result = CounterfactualResult.create_build_failure(context, generated_patch, f"Unexpected error: {e}", base_instance_id=base_instance_id)
            logger.error(f"Unexpected error during evaluation of {context.entry.instance_id}: {e}")

        finally:
            if result is not None:
                self.save_result(context, result)
            else:
                logger.error(f"No result generated for {context.entry.instance_id}")
                raise RuntimeError(f"No result generated for {context.entry.instance_id}")
