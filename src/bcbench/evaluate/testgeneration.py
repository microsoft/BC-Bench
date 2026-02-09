from collections.abc import Callable

from bcbench.collection.patch_utils import extract_file_paths_from_patch
from bcbench.dataset import TestEntry
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


class TestGenerationPipeline(EvaluationPipeline):
    """Pipeline for test-generation evaluation category.

    Workflow:
    1. Setup: clean repo, checkout base commit, build, then apply gold patch/problem statement
    2. Run agent: execute agent to generate test code
    3. Evaluate: build, run tests with expected failures, then apply original patch, build, run tests with expected passes

    Input modes (configured in copilot/config.yaml):
    - problem-statement: Agent receives bug description, generates tests from problem statement
    - gold-patch: Agent sees the fixed code, generates tests that verify the fix works

    Note: For test-generation, we build BEFORE applying the gold patch so the published app
    doesn't include the fix. The agent sees the fix in source but tests run against unfixed app.
    """

    def setup(self, context: EvaluationContext) -> None:
        setup_repo_prebuild(context.entry, context.repo_path)

        build_and_publish_projects(
            context.repo_path,
            context.entry.project_paths,
            context.container_name,
            context.username,
            context.password,
            context.entry.environment_setup_version,
        )

        # Apply gold patch / problem statement AFTER build so fix isn't included in published app
        setup_repo_postbuild(context.entry, context.repo_path, context.category)

    def run_agent(self, context: EvaluationContext, agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext) -> None:
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
