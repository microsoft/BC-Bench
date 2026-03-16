"""Dataset module for querying, validating and analyze dataset entries."""

from bcbench.dataset.dataset_entry import BaseDatasetEntry, BugFixTestGenEntry, TestEntry
from bcbench.dataset.reviewer import run_dataset_reviewer
from bcbench.types import EvaluationCategory

__all__ = [
    "BaseDatasetEntry",
    "BugFixTestGenEntry",
    "TestEntry",
    "get_entry_class",
    "run_dataset_reviewer",
]


def get_entry_class(category: EvaluationCategory) -> type[BaseDatasetEntry]:
    match category:
        case EvaluationCategory.BUG_FIX | EvaluationCategory.TEST_GENERATION:
            return BugFixTestGenEntry
        case _:
            raise ValueError(f"Unknown evaluation category: {category}")
