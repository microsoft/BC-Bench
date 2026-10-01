"""Dataset module for querying, validating and analyzing dataset entries."""

from importlib import import_module
from typing import TYPE_CHECKING

from bcbench.dataset.dataset_entry import BaseDatasetEntry, BugFixEntry, DataQueryEntry, NL2ALEntry, RepoGroundedEntry, TestEntry, TestGenEntry

if TYPE_CHECKING:
    from bcbench.dataset.codereview import ArticleId, CodeReviewEntry, CodeReviewEntryMetadata, ReviewComment, Severity
    from bcbench.dataset.extensibility_request import ExtRequestAdvisorEntry, ExtRequestImplementEntry, ExtRequestTriageEntry, ManagedLabel

_LAZY_EXPORTS = {
    "ArticleId": "bcbench.dataset.codereview",
    "CodeReviewEntry": "bcbench.dataset.codereview",
    "CodeReviewEntryMetadata": "bcbench.dataset.codereview",
    "ReviewComment": "bcbench.dataset.codereview",
    "Severity": "bcbench.dataset.codereview",
    "ExtRequestAdvisorEntry": "bcbench.dataset.extensibility_request",
    "ExtRequestImplementEntry": "bcbench.dataset.extensibility_request",
    "ExtRequestTriageEntry": "bcbench.dataset.extensibility_request",
    "ManagedLabel": "bcbench.dataset.extensibility_request",
}


def __getattr__(name: str) -> object:
    if name in _LAZY_EXPORTS:
        return getattr(import_module(_LAZY_EXPORTS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ArticleId",
    "BaseDatasetEntry",
    "BugFixEntry",
    "CodeReviewEntry",
    "CodeReviewEntryMetadata",
    "DataQueryEntry",
    "ExtRequestAdvisorEntry",
    "ExtRequestImplementEntry",
    "ExtRequestTriageEntry",
    "ManagedLabel",
    "NL2ALEntry",
    "RepoGroundedEntry",
    "ReviewComment",
    "Severity",
    "TestEntry",
    "TestGenEntry",
]
