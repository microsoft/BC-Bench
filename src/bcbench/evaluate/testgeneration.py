from collections.abc import Callable
from pathlib import Path

import yaml

from bcbench.collection.patch_utils import extract_file_paths_from_patch
from bcbench.config import get_config
from bcbench.dataset import TestEntry, TestGenEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import BuildError, NoTestsExtractedError, TestExecutionError
from bcbench.logger import get_logger, github_log_group
from bcbench.operations import (
    apply_patch,
    build_and_publish_projects,
    categorize_projects,
    clean_project_paths,
    copy_problem_statement_folder,
    extract_tests_from_patch,
    setup_repo_prebuild,
    stage_and_get_diff,
)
from bcbench.operations.bc_operations import run_test_suite
from bcbench.results.testgeneration import TestGenerationResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)
_config = get_config()

__all__ = ["TestGenerationPipeline", "_get_test_generation_input_mode"]


def _get_test_generation_input_mode() -> str:
    config_file: Path = _config.paths.agent_share_dir / "config.yaml"
    shared_config = yaml.safe_load(config_file.read_text())
    input_mode: str = shared_config.get("prompt", {}).get("test-generation-input", "problem-statement")

    valid_modes: set[str] = {"gold-patch", "problem-statement", "both"}
    if input_mode not in valid_modes:
        raise ValueError(f"Invalid test-generation-input mode: '{input_mode}'. Must be one of {valid_modes}. Note: Use hyphens, not underscores (e.g., 'gold-patch' not 'gold_patch')")

    return input_mode


class TestGenerationPipeline(EvaluationPipeline[TestGenEntry]):
    """Pipeline for test-generation evaluation category."""

    def _apply_input_postbuild(self, entry: TestGenEntry, repo_path: Path) -> None:
        input_mode = _get_test_generation_input_mode()
        logger.info(f"Test generation input mode: {input_mode}")
        match input_mode:
            case "gold-patch":
                apply_patch(repo_path, entry.patch, f"{entry.instance_id} gold patch")
            case "both":
                apply_patch(repo_path, entry.patch, f"{entry.instance_id} gold patch")
                copy_problem_statement_folder(entry, repo_path)
            case "problem-statement":
                copy_problem_statement_folder(entry, repo_path)
            case _:
                raise ValueError(f"Unhandled test generation input mode: {input_mode}")

    def setup_workspace(self, entry: TestGenEntry, repo_path: Path) -> None:
        setup_repo_prebuild(entry, repo_path)
        self._apply_input_postbuild(entry, repo_path)

    def setup(self, context: EvaluationContext[TestGenEntry]) -> None:
        setup_repo_prebuild(context.entry, context.repo_path)

        build_and_publish_projects(
            context.repo_path,
            context.entry.project_paths,
            context.get_container(),
            context.entry.environment_setup_version,
        )

        self._apply_input_postbuild(context.entry, context.repo_path)

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

            result = TestGenerationResult.create_success(context, generated_patch)
            logger.info(f"Successfully completed {context.entry.instance_id}")

        except BuildError as e:
            result = TestGenerationResult.create_build_failure(context, generated_patch, str(e))
            logger.exception(f"Build failed during evaluation of {context.entry.instance_id}")

        except TestExecutionError as e:
            if e.expectation == "Fail":
                result = TestGenerationResult.create_pre_patch_failure(context, generated_patch, "Generated tests Passed pre-patch\n" + str(e))
            else:
                result = TestGenerationResult.create_post_patch_failure(context, generated_patch, "Generated tests Failed post-patch\n" + str(e))

            logger.exception(f"Tests failed during evaluation of {context.entry.instance_id}")

        except NoTestsExtractedError:
            result = TestGenerationResult.create_no_tests_extracted(context, generated_patch, "No tests extracted from generated patch")
            raise

        finally:
            if result is not None:
                self.save_result(context, result)
            else:
                logger.error(f"No result generated for {context.entry.instance_id}")
                raise RuntimeError(f"No result generated for {context.entry.instance_id}")
