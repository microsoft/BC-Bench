"""Category-owned facts and behaviour, replacing the per-property lookup tables on `EvaluationCategory`."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from bcbench_core.agent.harness import AgentResult
from bcbench_core.evaluation import Category

from bcbench.dataset import BaseDatasetEntry
from bcbench.results import BaseEvaluationResult, EvaluationResultSummary, LeaderboardAggregate
from bcbench.types import AgentConfig, DatasetTier, EvaluationCategory, EvaluationContext

__all__ = ["CategoryDefinition", "Judge", "Runner"]

# GitHub Actions runner labels; only categories that build BaseApp need the self-hosted runners
type Runner = Literal["GitHub-BCBench", "ubuntu-latest", "windows-latest"]

# LLM judges configured under `judges` in agent/shared/config.yaml
type Judge = Literal["code-review", "lm-checklist"]


@dataclass(frozen=True)
class CategoryDefinition[E: BaseDatasetEntry]:
    category: EvaluationCategory
    dataset_files: Mapping[DatasetTier, str]
    entry_type: type[E]
    result_type: type[BaseEvaluationResult]
    # Per-run summaries and their multi-run leaderboard aggregates
    summary_type: type[EvaluationResultSummary]
    aggregate_type: type[LeaderboardAggregate]
    # bc-eval evaluators (evaluator/scores.py) uploaded for this category, and the one reported as CoreScore
    evaluators: tuple[str, ...]
    core_score: str
    judge: Judge | None
    runner: Runner
    # Whether evaluating builds/runs AL code and therefore needs a BC container
    requires_container: bool
    # Development scenarios (e.g. bug-fix) get direct container access; production-like ones (e.g. data-query) must
    # use the exposed access methods, such as BC MCP, so the agent never sees the container credentials
    pass_bc_credentials: bool
    # Builds the category's behaviour from the agent config; it is then evaluated once per `EvaluationContext`
    make: Callable[[AgentConfig], Category[EvaluationContext[E], BaseEvaluationResult]]

    def dataset_path(self, dataset_dir: Path, tier: DatasetTier) -> Path:
        if tier not in self.dataset_files:
            raise ValueError(f"{self.category.value} has no {tier.value} dataset")
        return dataset_dir / self.dataset_files[tier]

    def timeout_result(self, context: EvaluationContext[E], observed: AgentResult) -> BaseEvaluationResult:
        """The result for an agent that timed out, which is not graded; `on_timeout` for `evaluate_task`."""
        return self.result_type.create_agent_timeout_failure(context, observed)

    @property
    def base_entry_type(self) -> type[BaseDatasetEntry]:
        """`entry_type` for callers that select the category at runtime and only know it as `CategoryDefinition[Any]`, e.g. `EvaluationCategory.entry_class`."""
        return self.entry_type
