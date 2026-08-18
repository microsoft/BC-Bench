from collections.abc import Callable
from pathlib import Path

from bcbench.collection.patch_utils import extract_file_paths_from_patch, split_patch_by_projects
from bcbench.dataset import BugFixEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.evaluate.red_green import run_red_green_check
from bcbench.exceptions import BuildError, NoTestsExtractedError, PatchApplicationError, TestExecutionError
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
from bcbench.results.bugfix import BugFixResult, FixCheckOutcome, TestCheckOutcome
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["BugFixPipeline"]


def _read_patched_files(repo_path: Path, patch: str) -> dict[str, str]:
    paths = extract_file_paths_from_patch(patch)
    return {path: (repo_path / path).read_text(encoding="utf-8") for path in paths if (repo_path / path).is_file()}


def _run_test_check(context: EvaluationContext[BugFixEntry], test_patch: str, app_projects: list[str]) -> TestCheckOutcome:
    """Validate the agent's test gold-anchored: it must fail on base code and pass with the gold patch."""
    clean_project_paths(context.repo_path, app_projects)

    try:
        generated_tests = extract_tests_from_patch(test_patch, _read_patched_files(context.repo_path, test_patch))
    except NoTestsExtractedError as e:
        logger.warning(f"{context.entry.instance_id}: no tests extracted from the agent patch")
        return TestCheckOutcome(error_message=str(e))

    try:
        run_red_green_check(
            repo_path=context.repo_path,
            entry=context.entry,
            container=context.get_container(),
            generated_tests=generated_tests,
            # Every project, not just the test projects: the agent may have published its own fix
            # into the container, and reverting sources alone would leave the red run unable to fail.
            initial_build_projects=context.entry.project_paths,
            app_projects=app_projects,
        )
    except PatchApplicationError as e:
        logger.exception(f"Test check patch application failed for {context.entry.instance_id}")
        return TestCheckOutcome(error_message=f"Test check patch application failed\n{e}")
    except BuildError as e:
        logger.exception(f"Test check build failed for {context.entry.instance_id}")
        return TestCheckOutcome(error_message=f"Test check build failed\n{e}")
    except TestExecutionError as e:
        if e.expectation == "Fail":
            return TestCheckOutcome(build=True, error_message=f"Generated test passed pre-patch\n{e}")
        return TestCheckOutcome(build=True, pre_patch_failed=True, error_message=f"Generated test failed post-patch\n{e}")

    return TestCheckOutcome(build=True, pre_patch_failed=True, post_patch_passed=True)


def _run_fix_check(context: EvaluationContext[BugFixEntry], app_patch: str) -> FixCheckOutcome:
    """Validate the agent's fix against the gold test patch, from a workspace reset to base."""
    # Resets the working tree (git reset --hard + clean -fd): must run after any stage that
    # still needs to read the agent's changes from disk.
    entry = context.entry
    container = context.get_container()

    setup_repo_prebuild(entry, context.repo_path)
    # setup_repo_prebuild discards the app.json runtime edits, so re-apply them before building.
    set_runtime_version(context.repo_path, entry.project_paths)

    try:
        if app_patch.strip():
            apply_patch(context.repo_path, app_patch, f"{entry.instance_id} agent fix")
        apply_patch(context.repo_path, entry.test_patch, f"{entry.instance_id} test patch")
        build_and_publish_projects(context.repo_path, entry.project_paths, container, entry.environment_setup_version)
        run_tests(entry, container)
    except PatchApplicationError as e:
        logger.exception(f"Fix check patch application failed for {entry.instance_id}")
        return FixCheckOutcome(error_message=f"Fix check patch application failed\n{e}")
    except BuildError as e:
        logger.exception(f"Fix check build failed for {entry.instance_id}")
        return FixCheckOutcome(error_message=f"Fix check build failed\n{e}")
    except TestExecutionError as e:
        logger.exception(f"Gold tests failed for {entry.instance_id}")
        return FixCheckOutcome(build=True, error_message=f"Gold tests failed\n{e}")

    return FixCheckOutcome(build=True, passed=True)


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

    def run_agent(self, context: EvaluationContext[BugFixEntry], agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[BugFixEntry]) -> None:
        test_projects, app_projects = categorize_projects(context.entry.project_paths)

        generated_patch = stage_and_get_diff(context.repo_path)
        app_patch, test_patch = split_patch_by_projects(generated_patch, test_projects)

        # Both stages always run: a bad test must never hide a good fix, or vice versa.
        test_outcome = _run_test_check(context, test_patch, app_projects)
        fix_outcome = _run_fix_check(context, app_patch)

        result = BugFixResult.from_outcomes(context, generated_patch, test_outcome, fix_outcome)
        self.save_result(context, result)

        logger.info(f"{context.entry.instance_id}: resolved={result.resolved} test_correct={result.test_correct} fix_correct={result.fix_correct}")
