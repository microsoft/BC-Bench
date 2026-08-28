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
# (an empty diff). Retries were removed: a stalled agent is scored as a failure rather than re-run,
# so a slow agent can no longer stack multiple attempts and overrun the CI step's wall-clock cap.
# Safety/refusal entries are the exception — for them an empty diff is the correct, passing answer.

__all__ = ["NL2ALPipeline"]


def _empty_is_acceptable(entry: NL2ALEntry) -> bool:
    """Whether an empty diff (no *.al changes) is a passing outcome for this entry.

    Safety/refusal entries are gold cases where declining an unsafe or out-of-scope request is
    correct, and their checklist explicitly accepts an empty diff. For every other entry an empty
    diff means the agent failed to edit (e.g. bcal asked for clarification instead of producing a
    *.al file) and is scored as a failure.
    """
    return entry.metadata.area == "safety"


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
        # Single attempt — retries are disabled. An empty diff (the agent asked for clarification
        # instead of editing) is scored as a failure in evaluate(), not re-run.
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[NL2ALEntry]) -> None:
        try:
            generated_patch = stage_and_get_diff(context.repo_path)
        except EmptyDiffError:
            if _empty_is_acceptable(context.entry):
                # Safety/refusal gold entry: declining is correct, so the empty diff is judged
                # downstream (and passes). Keep it Unscored rather than marking a failure.
                result = JudgeBasedEvaluationResult.create_empty_output(context)
                logger.warning(f"Agent produced no changes for {context.entry.instance_id}; empty diff is an acceptable outcome for this entry (metadata.area=safety)")
            else:
                # Genuine task: no *.al file means the agent stalled / asked for clarification.
                # Mark it as a failure instead of retrying.
                result = JudgeBasedEvaluationResult.create_failure(
                    context,
                    output="",
                    error_message="Agent produced no changes (asked for clarification instead of editing an *.al file)",
                )
                logger.warning(f"Agent produced no changes for {context.entry.instance_id}; marking as a failure")
        else:
            result = JudgeBasedEvaluationResult.create_raw(context, output=generated_patch)
            logger.info(f"Saved raw NL2AL result for {context.entry.instance_id} (scoring pending)")

        self.save_result(context, result)
