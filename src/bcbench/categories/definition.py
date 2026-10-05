"""The contract every evaluation category fulfils."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Literal, TypeVar

from bcbench.dataset import BaseDatasetEntry, RepoGroundedEntry
from bcbench.types import EvaluationCategory

# Covariant so a definition for a specific entry type is usable wherever any definition is expected
E_co = TypeVar("E_co", bound=BaseDatasetEntry, covariant=True)

# GitHub Actions runner labels; only categories that build BaseApp need the self-hosted runners
type Runner = Literal["GitHub-BCBench", "ubuntu-latest", "windows-latest"]


@dataclass(frozen=True)
class CategoryDefinition(Generic[E_co]):  # noqa: UP046 - PEP 695 syntax cannot declare covariance explicitly
    category: EvaluationCategory
    dataset_file: str
    entry_type: type[E_co]
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

    def load_entries(self, dataset_dir: Path, entry_id: str | None = None) -> Sequence[E_co]:
        return self.entry_type.load(self.dataset_path(dataset_dir), entry_id=entry_id)
