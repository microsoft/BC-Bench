import os
import subprocess
from pathlib import Path

from bcbench.dataset import NL2ALEntry
from bcbench.evaluate.base import AgentRunner, EvaluationPipeline
from bcbench.exceptions import EmptyDiffError
from bcbench.github_actions import github_log_group
from bcbench.logger import get_logger
from bcbench.operations import copy_symbol_apps, remove_tree, stage_and_get_diff
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

# bcal nondeterministically asks for clarification instead of editing, producing no *.al file
# (surfaces downstream as an empty diff -> auto-0). Re-run the agent on a clean workspace a couple
# of times before accepting an empty result. Empty runs fail fast, so this stays within the CI step
# budget; a non-empty diff breaks the loop immediately.
_EMPTY_DIFF_MAX_ATTEMPTS = 3

__all__ = ["NL2ALPipeline"]


def _reset_repo_path(repo_path: Path) -> None:
    if repo_path.exists():
        remove_tree(repo_path)
    repo_path.mkdir(parents=True, exist_ok=True)


def _git_init_and_commit(repo_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial AL project scaffold"],
        cwd=repo_path,
        capture_output=True,
        check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "bcbench", "GIT_AUTHOR_EMAIL": "bcbench@localhost", "GIT_COMMITTER_NAME": "bcbench", "GIT_COMMITTER_EMAIL": "bcbench@localhost"},
    )


class NL2ALPipeline(EvaluationPipeline[NL2ALEntry]):
    """Pipeline for NL2AL evaluation category — generate AL code from natural language."""

    def setup_workspace(self, entry: NL2ALEntry, repo_path: Path) -> None:
        _reset_repo_path(repo_path)
        copy_symbol_apps(repo_path / entry.project_paths[0], entry.environment_setup_version)
        _git_init_and_commit(repo_path)

    def setup(self, context: EvaluationContext[NL2ALEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext[NL2ALEntry], agent_runner: AgentRunner[NL2ALEntry]) -> None:
        for attempt in range(1, _EMPTY_DIFF_MAX_ATTEMPTS + 1):
            with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id} (attempt {attempt}/{_EMPTY_DIFF_MAX_ATTEMPTS})"):
                context.metrics, context.experiment = agent_runner(context)

            if attempt == _EMPTY_DIFF_MAX_ATTEMPTS:
                break
            try:
                stage_and_get_diff(context.repo_path)
            except EmptyDiffError:
                logger.warning(f"nl2al agent produced an empty diff for {context.entry.instance_id} (attempt {attempt}/{_EMPTY_DIFF_MAX_ATTEMPTS}); retrying with a clean workspace")
                self.setup_workspace(context.entry, context.repo_path)
            else:
                break

    def evaluate(self, context: EvaluationContext[NL2ALEntry]) -> None:
        try:
            generated_patch = stage_and_get_diff(context.repo_path)
        except EmptyDiffError:
            result = JudgeBasedEvaluationResult.create_empty_output(context)
            logger.warning(f"Agent produced no changes for {context.entry.instance_id}")
        else:
            result = JudgeBasedEvaluationResult.create_raw(context, output=generated_patch)
            logger.info(f"Saved raw NL2AL result for {context.entry.instance_id} (scoring pending)")

        self.save_result(context, result)
