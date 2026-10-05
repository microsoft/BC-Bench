"""The contract every evaluation category fulfils."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from bcbench.dataset import BaseDatasetEntry, RepoGroundedEntry
from bcbench.evaluate import EvaluationPipeline
from bcbench.types import EvaluationCategory

# GitHub Actions runner labels; only categories that build BaseApp need the self-hosted runners
type Runner = Literal["GitHub-BCBench", "ubuntu-latest", "windows-latest"]


@dataclass(frozen=True)
class CategoryDefinition[E: BaseDatasetEntry]:
    category: EvaluationCategory
    dataset_file: str
    entry_type: type[E]
    make_pipeline: Callable[[], EvaluationPipeline[E]]
    # bc-eval evaluators (evaluator/scores.py) uploaded for this category, and the one reported as CoreScore
    evaluators: tuple[str, ...]
    core_score: str
    runner: Runner
    # Whether evaluating builds/runs AL code and therefore needs a BC container
    requires_container: bool
    # Development scenarios (e.g. bug-fix) get direct container access; production-like ones (e.g. data-query) must
    # use the exposed access methods, such as BC MCP, so the agent never sees the container credentials
    pass_bc_credentials: bool

    @property
    def requires_repo(self) -> bool:
        return issubclass(self.entry_type, RepoGroundedEntry)

    def dataset_path(self, dataset_dir: Path) -> Path:
        return dataset_dir / self.dataset_file

    def load_entries(self, dataset_dir: Path, entry_id: str | None = None) -> Sequence[E]:
        return self.entry_type.load(self.dataset_path(dataset_dir), entry_id=entry_id)
