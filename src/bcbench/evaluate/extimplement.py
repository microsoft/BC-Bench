from collections.abc import Callable
from pathlib import Path
from shutil import rmtree

from bcbench.config import get_config
from bcbench.dataset import ExtImplementEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import EmptyDiffError
from bcbench.github_actions import github_log_group
from bcbench.logger import get_logger
from bcbench.operations import fetch_commit_if_missing, set_runtime_version, setup_repo_prebuild, stage_and_get_diff
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)
_config = get_config()

__all__ = ["ExtImplementPipeline"]


def _copy_problem_statement(entry: ExtImplementEntry, repo_path: Path) -> None:
    """Copy the extensibility request folder into the repo so the agent can read it locally."""
    from shutil import copytree

    source_dir: Path = entry.problem_statement_dir
    dest_dir: Path = repo_path / _config.file_patterns.problem_statement_dest_dir

    if dest_dir.exists():
        rmtree(dest_dir)

    copytree(source_dir, dest_dir)
    logger.info(f"Copied extensibility request folder from {source_dir} to {dest_dir}")


class ExtImplementPipeline(EvaluationPipeline[ExtImplementEntry]):
    """Pipeline for the ext-implement category — implement an extensibility request as an AL change.

    Judge-based: no BC container, no build, no tests. The repo is checked out at the entry's base
    commit and the agent adds the requested extension point. The resulting diff is scored downstream
    by an LLM judge against the entry checklist.
    """

    def setup_workspace(self, entry: ExtImplementEntry, repo_path: Path) -> None:
        # Extensibility base commits may be pre-squash commits missing from local/CI clones.
        fetch_commit_if_missing(repo_path, entry.base_commit)
        setup_repo_prebuild(entry, repo_path)
        _copy_problem_statement(entry, repo_path)
        set_runtime_version(repo_path, entry.project_paths)

    def setup(self, context: EvaluationContext[ExtImplementEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext[ExtImplementEntry], agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[ExtImplementEntry]) -> None:
        try:
            generated_patch = stage_and_get_diff(context.repo_path)
        except EmptyDiffError:
            result = JudgeBasedEvaluationResult.create_empty_output(context)
            logger.warning(f"Agent produced no changes for {context.entry.instance_id}")
        else:
            result = JudgeBasedEvaluationResult.create_raw(context, output=generated_patch)
            logger.info(f"Saved raw ext-implement result for {context.entry.instance_id} (scoring pending)")

        self.save_result(context, result)
