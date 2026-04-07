from collections.abc import Callable

from bcbench.collection.patch_utils import extract_file_paths_from_patch
from bcbench.dataset import TestEntry, TestGenEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import BuildError, NoTestsExtractedError, TestExecutionError
from bcbench.logger import get_logger, github_log_group
from bcbench.operations import (
    apply_patch,
    build_and_publish_projects,
    categorize_projects,
    clean_project_paths,
    extract_tests_from_patch,
    setup_repo_postbuild,
    setup_repo_prebuild,
    stage_and_get_diff,
)
from bcbench.operations.bc_operations import run_test_suite
from bcbench.results.testgeneration import TestGenerationResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["TestGenerationPipeline"]


class TestGenerationPipeline(EvaluationPipeline[TestGenEntry]):
    """Pipeline for test-generation evaluation category."""

    def setup(self, context: EvaluationContext[TestGenEntry]) -> None:
        setup_repo_prebuild(context.entry, context.repo_path)

        build_and_publish_projects(
            context.repo_path,
            context.entry.project_paths,
            context.get_container(),
            context.entry.environment_setup_version,
        )

        setup_repo_postbuild(context.entry, context.repo_path, context.category)

    def run_agent(self, context: EvaluationContext[TestGenEntry], agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[TestGenEntry]) -> None:
        container = context.get_container()
        test_projects, app_projects = categorize_projects(context.entry.project_paths)

        # Clean app projects to revert any unintended agent changes before capturing diff
        # Evaluation focuses on valid changes (test code), treating unintended modifications as out-of-scope noise
        clean_project_paths(context.repo_path, app_projects)

        generated_patch: str = stage_and_get_diff(context.repo_path)

        # Read file contents from the local repo for test extraction
        file_contents: dict[str, str] = {}
        for file_path in extract_file_paths_from_patch(generated_patch):
            full_path = context.repo_path / file_path
            if full_path.exists():
                file_contents[file_path] = full_path.read_text(encoding="utf-8")

        result: TestGenerationResult | None = None

        try:
            generated_tests: list[TestEntry] = extract_tests_from_patch(generated_patch, file_contents)

            build_and_publish_projects(
                context.repo_path,
                test_projects,
                container,
                context.entry.environment_setup_version,
            )
            run_test_suite(generated_tests, "Fail", container)

            apply_patch(context.repo_path, context.entry.patch, f"{context.entry.instance_id} patch")

            build_and_publish_projects(
                context.repo_path,
                app_projects,
                container,
                context.entry.environment_setup_version,
            )
            run_test_suite(generated_tests, "Pass", container)

            result = TestGenerationResult.create_success(context, generated_patch, pre_patch_failed=True, post_patch_passed=True)
            logger.info(f"Successfully completed {context.entry.instance_id}")

        except BuildError as e:
            result = TestGenerationResult.create_build_failure(context, generated_patch, str(e))
            logger.error(f"Build failed during evaluation of {context.entry.instance_id}: {e}")

        except TestExecutionError as e:
            if e.expectation == "Fail":
                result = TestGenerationResult.create_test_failure(context, generated_patch, "Generated tests Passed pre-patch\n" + str(e), pre_patch_failed=False)
            else:
                result = TestGenerationResult.create_test_failure(context, generated_patch, "Generated tests Failed post-patch\n" + str(e), pre_patch_failed=True, post_patch_passed=False)

            logger.error(f"Tests failed during evaluation of {context.entry.instance_id}: {e}")

        except NoTestsExtractedError:
            result = TestGenerationResult.create_no_tests_extracted(context, generated_patch, "No tests extracted from generated patch")
            raise

        finally:
            if result is not None:
                self.save_result(context, result)
            else:
                logger.error(f"No result generated for {context.entry.instance_id}")
                raise RuntimeError(f"No result generated for {context.entry.instance_id}")
