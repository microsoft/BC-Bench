from dataclasses import dataclass
from pathlib import Path

from bcbench_core.evaluation import EvaluationRequest
from bcbench_core.types import AgentExecution, AgentMetrics, AgentMetricsContract, AgentRuntimeConfig

from bcbench.agent import get_copilot_version, get_pr_review_version, run_copilot_agent, run_pr_review_agent
from bcbench.dataset import CodeReviewEntry
from bcbench.exceptions import AgentTimeoutError
from bcbench.types import EvaluationCategory, PRReviewMetrics


@dataclass(frozen=True)
class CopilotCodeReviewAgent:
    runtime: AgentRuntimeConfig | None

    name = "GitHub Copilot"
    metrics_contract = AgentMetricsContract(
        AgentMetrics,
        frozenset({"execution_time", "llm_duration", "ai_credits", "turn_count", "tool_usage"}),
    )

    @property
    def version(self) -> str:
        return get_copilot_version()

    def run(self, request: EvaluationRequest[CodeReviewEntry]) -> AgentExecution:
        try:
            metrics, experiment = run_copilot_agent(
                entry=request.entry,
                repo_path=request.repo_path,
                model=request.model,
                category=EvaluationCategory.CODE_REVIEW,
                output_dir=request.result_dir,
                runtime=self.runtime,
                prompt=request.prompt,
            )
        except AgentTimeoutError as error:
            return AgentExecution(
                metrics=error.metrics,
                experiment=error.config,
                timed_out=True,
            )
        return AgentExecution(metrics=metrics, experiment=experiment)


@dataclass(frozen=True)
class PRReviewCodeReviewAgent:
    engine_path: Path | None
    min_severity: str | None = None

    name = "BC PR Review"
    metrics_contract = AgentMetricsContract(
        PRReviewMetrics,
        frozenset({"execution_time", "prompt_tokens", "completion_tokens", "total_tokens", "ai_credits"}),
    )

    @property
    def version(self) -> str:
        return get_pr_review_version(self.engine_path)

    def run(self, request: EvaluationRequest[CodeReviewEntry]) -> AgentExecution:
        try:
            metrics, experiment = run_pr_review_agent(
                entry=request.entry,
                model=request.model,
                repo_path=request.repo_path,
                output_dir=request.result_dir,
                engine_path=self.engine_path,
                min_severity=self.min_severity,
            )
        except AgentTimeoutError as error:
            return AgentExecution(
                metrics=error.metrics,
                experiment=error.config,
                timed_out=True,
            )
        return AgentExecution(metrics=metrics, experiment=experiment)
