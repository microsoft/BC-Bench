from pathlib import Path

from bcbench.collection.patch_utils import extract_file_paths_from_patch, separate_patches
from bcbench.config import get_config
from bcbench.dataset import BugFixEntry
from bcbench.evaluate.base import AgentRunner, EvaluationPipeline
from bcbench.exceptions import BuildError, EmptyDiffError, NoTestsExtractedError, TestExecutionError
from bcbench.github_actions import github_log_group
from bcbench.logger import get_logger
from bcbench.operations import (
    apply_patch,
    build_and_publish_projects,
    categorize_projects,
    clean_project_paths,
    copy_problem_statement_folder,
    extract_tests_from_patch,
    run_tests,
    set_runtime_version,
    setup_repo_prebuild,
    stage_and_get_diff,
)
from bcbench.operations.bc_operations import run_test_suite
from bcbench.results.bugfix import BugFixResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)
_config = get_config()

__all__ = ["BugFixPipeline"]


class BugFixPipeline(EvaluationPipeline[BugFixEntry]):
    """Pipeline for bug-fix evaluation category."""

    def setup_workspace(self, entry: BugFixEntry, repo_path: Path) -> None:
        setup_repo_prebuild(entry, repo_path)
        copy_problem_statement_folder(entry, repo_path)
        set_runtime_version(repo_path, entry.project_paths)

    def setup(self, context: EvaluationContext[BugFixEntry]) -> None:
        setup_repo_prebuild(context.entry, context.repo_path)

        build_and_publish_projects(
            context.repo_path,
            context.entry.project_paths,
            context.get_container(),
            context.entry.environment_setup_version,
        )

        copy_problem_statement_folder(context.entry, context.repo_path)
        set_runtime_version(context.repo_path, context.entry.project_paths)

    def run_agent(self, context: EvaluationContext[BugFixEntry], agent_runner: AgentRunner[BugFixEntry]) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[BugFixEntry]) -> None:
        container = context.get_container()
        test_projects, app_projects = categorize_projects(context.entry.project_paths)

        try:
            generated_patch = stage_and_get_diff(context.repo_path)
        except EmptyDiffError as error:
            self.save_result(
                context,
                BugFixResult.create_verification_failure(context, "", str(error), build=False),
            )
            return

        _, generated_fix_patch, generated_test_patch = separate_patches(generated_patch, _config.file_patterns.test_project_identifiers)
        if not generated_fix_patch.strip():
            self.save_result(
                context,
                BugFixResult.create_verification_failure(
                    context,
                    generated_patch,
                    "Agent produced tests but no product-code fix.",
                    build=False,
                ),
            )
            return

        file_contents: dict[str, str] = {}
        for file_path in extract_file_paths_from_patch(generated_test_patch):
            full_path = context.repo_path / file_path
            if full_path.exists():
                file_contents[file_path] = full_path.read_text(encoding="utf-8")

        try:
            generated_tests = extract_tests_from_patch(generated_test_patch, file_contents)
        except NoTestsExtractedError as error:
            self.save_result(
                context,
                BugFixResult.create_verification_failure(
                    context,
                    generated_patch,
                    str(error),
                    build=False,
                ),
            )
            return

        result: BugFixResult | None = None
        generated_test_pre_patch_failed = False
        generated_test_post_patch_passed = False

        try:
            clean_project_paths(context.repo_path, app_projects)
            build_and_publish_projects(
                context.repo_path,
                test_projects,
                container,
                context.entry.environment_setup_version,
            )
            run_test_suite(generated_tests, "Fail", container)
            generated_test_pre_patch_failed = True

            apply_patch(context.repo_path, generated_fix_patch, f"{context.entry.instance_id} generated fix patch")
            build_and_publish_projects(
                context.repo_path,
                [*app_projects, *test_projects],
                container,
                context.entry.environment_setup_version,
            )
            run_test_suite(generated_tests, "Pass", container)
            generated_test_post_patch_passed = True

            clean_project_paths(context.repo_path, test_projects)
            apply_patch(context.repo_path, context.entry.test_patch, f"{context.entry.instance_id} benchmark test patch")
            build_and_publish_projects(
                context.repo_path,
                [*app_projects, *test_projects],
                container,
                context.entry.environment_setup_version,
            )
            run_tests(context.entry, container)

            result = BugFixResult.create_success(context, generated_patch)
            logger.info(f"Successfully completed {context.entry.instance_id}")

        except BuildError as e:
            result = BugFixResult.create_verification_failure(
                context,
                generated_patch,
                str(e),
                build=False,
                generated_test_pre_patch_failed=generated_test_pre_patch_failed,
                generated_test_post_patch_passed=generated_test_post_patch_passed,
            )
            logger.exception(f"Build failed during evaluation of {context.entry.instance_id}")

        except TestExecutionError as e:
            if not generated_test_pre_patch_failed:
                error_message = "Generated tests passed before the product-code fix\n" + str(e)
            elif not generated_test_post_patch_passed:
                error_message = "Generated tests failed after the product-code fix\n" + str(e)
            else:
                error_message = "Benchmark tests failed after the generated fix\n" + str(e)

            result = BugFixResult.create_verification_failure(
                context,
                generated_patch,
                error_message,
                build=True,
                generated_test_pre_patch_failed=generated_test_pre_patch_failed,
                generated_test_post_patch_passed=generated_test_post_patch_passed,
            )
            logger.exception(f"Tests failed during evaluation of {context.entry.instance_id}")

        finally:
            if result is not None:
                self.save_result(context, result)
            else:
                logger.error(f"No result generated for {context.entry.instance_id}")
                raise RuntimeError(f"No result generated for {context.entry.instance_id}")
