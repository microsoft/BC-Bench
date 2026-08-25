"""Pipeline for the extensibility-request-triage category — triage a single extensibility request.

The agent runs the `extensibility-request-triage` custom agent (instructions-based) in emit-only mode: it reads the request text from the prompt,
analyses the standard AL source checked out at the entry's base commit, and writes its `Final_Output`
decision (managed labels + advisory comment + open/closed state) to `triage_result.json` in the repo
root instead of applying it via `gh`. Like NL2AL and extensibility-request-implement, the pipeline only
persists that raw decision; scoring is performed downstream by the LMChecklist judge against the entry's
`expected` checklist.
"""

from pathlib import Path

from bcbench.dataset import ExtRequestTriageEntry
from bcbench.evaluate.base import AgentRunner, EvaluationPipeline
from bcbench.github_actions import github_log_group
from bcbench.logger import get_logger
from bcbench.operations import setup_repo_prebuild
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["TRIAGE_RESULT_FILE", "ExtRequestTriagePipeline"]

TRIAGE_RESULT_FILE = "triage_result.json"


class ExtRequestTriagePipeline(EvaluationPipeline[ExtRequestTriageEntry]):
    """Pipeline for the extensibility-request-triage category — no BC container, no build, no tests."""

    def setup_workspace(self, entry: ExtRequestTriageEntry, repo_path: Path) -> None:
        setup_repo_prebuild(entry, repo_path)
        (repo_path / TRIAGE_RESULT_FILE).unlink(missing_ok=True)

    def setup(self, context: EvaluationContext[ExtRequestTriageEntry]) -> None:
        self.setup_workspace(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext[ExtRequestTriageEntry], agent_runner: AgentRunner[ExtRequestTriageEntry]) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext[ExtRequestTriageEntry]) -> None:
        result_path = context.repo_path / TRIAGE_RESULT_FILE
        raw = result_path.read_text(encoding="utf-8").strip() if result_path.exists() else ""

        if not raw:
            result = JudgeBasedEvaluationResult.create_empty_output(context)
            logger.warning(f"Agent produced no {TRIAGE_RESULT_FILE} for {context.entry.instance_id}")
        else:
            result = JudgeBasedEvaluationResult.create_raw(context, output=raw)
            logger.info(f"Saved raw extensibility-request-triage result for {context.entry.instance_id} (scoring pending)")

        self.save_result(context, result)
