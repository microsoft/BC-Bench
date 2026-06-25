import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from bcbench.dataset import HelloWorldEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.exceptions import EmptyDiffError
from bcbench.github_actions import github_log_group
from bcbench.logger import get_logger
from bcbench.operations import stage_and_get_diff
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["HelloWorldPipeline"]


def _force_remove_readonly(func: Callable, path: str, _: object) -> None:
    Path(path).chmod(0o666)
    func(path)


def _reset_repo_path(repo_path: Path) -> None:
    if repo_path.exists():
        shutil.rmtree(repo_path, onexc=_force_remove_readonly)
    repo_path.mkdir(parents=True, exist_ok=True)


def _git_init_and_commit(repo_path: Path) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "bcbench", "GIT_AUTHOR_EMAIL": "bcbench@localhost", "GIT_COMMITTER_NAME": "bcbench", "GIT_COMMITTER_EMAIL": "bcbench@localhost"}
    subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial hello-world scaffold"], cwd=repo_path, capture_output=True, check=True, env=env)


class HelloWorldPipeline(EvaluationPipeline[HelloWorldEntry]):
    """Imaginary demo pipeline: the agent writes a tiny AL greeting codeunit.

    Self-contained (no BC container, no symbols), so it doubles as the smallest possible
    example of a category. Scoring is judge-based and happens downstream, so evaluate()
    only captures the agent's diff as the raw output.
    """

    def setup_workspace(self, entry: HelloWorldEntry, repo_path: Path) -> None:
        _reset_repo_path(repo_path)
        (repo_path / "README.md").write_text(f"# {entry.instance_id}\n\n{entry.get_task()}\n", encoding="utf-8")
        _git_init_and_commit(repo_path)

    def setup(self, context: EvaluationContext[HelloWorldEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext[HelloWorldEntry], agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[HelloWorldEntry]) -> None:
        try:
            generated_patch = stage_and_get_diff(context.repo_path)
        except EmptyDiffError:
            result = JudgeBasedEvaluationResult.create_empty_output(context)
            logger.warning(f"Agent produced no changes for {context.entry.instance_id}")
        else:
            result = JudgeBasedEvaluationResult.create_raw(context, output=generated_patch)
            logger.info(f"Saved raw hello-world result for {context.entry.instance_id} (scoring pending)")

        self.save_result(context, result)
