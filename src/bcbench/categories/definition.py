"""The contract every evaluation category fulfils."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, assert_never

from bcbench.config import JudgeConfig
from bcbench.dataset import BaseDatasetEntry, RepoGroundedEntry
from bcbench.evaluate import EvaluationPipeline
from bcbench.results import BaseEvaluationResult, EvaluationResultSummary, LeaderboardAggregate
from bcbench.types import EvaluationCategory

# GitHub Actions runner labels; only categories that build BaseApp need the self-hosted runners
type Runner = Literal["GitHub-BCBench", "ubuntu-latest", "windows-latest"]

# LLM judges configured under `judges` in agent/shared/config.yaml
type Judge = Literal["code-review", "lm-checklist"]


@dataclass(frozen=True)
class CategoryDefinition[E: BaseDatasetEntry]:
    category: EvaluationCategory
    dataset_file: str
    entry_type: type[E]
    pipeline_type: type[EvaluationPipeline[E]]
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

    @property
    def requires_repo(self) -> bool:
        return issubclass(self.entry_type, RepoGroundedEntry)

    @property
    def result_type(self) -> type[BaseEvaluationResult]:
        return self.pipeline_type.result_type

    def dataset_path(self, dataset_dir: Path) -> Path:
        return dataset_dir / self.dataset_file

    def load_entries(self, dataset_dir: Path, entry_id: str | None = None) -> Sequence[E]:
        return self.entry_type.load(self.dataset_path(dataset_dir), entry_id=entry_id)

    def make_pipeline(self) -> EvaluationPipeline[E]:
        return self.pipeline_type()

    def judge_model(self, judges: JudgeConfig) -> str | None:
        match self.judge:
            case None:
                return None
            case "code-review":
                return judges.code_review_model
            case "lm-checklist":
                return judges.lm_checklist_model
            case _:
                assert_never(self.judge)
