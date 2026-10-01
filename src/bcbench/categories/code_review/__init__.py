"""Code-review dataset, evaluation, and scoring policy."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bcbench.categories.code_review.definition import build_definition
    from bcbench.categories.code_review.entry import ArticleId, CodeReviewEntry, CodeReviewEntryMetadata, ReviewComment, Severity
    from bcbench.categories.code_review.pipeline import CodeReviewPipeline
    from bcbench.categories.code_review.results import CodeReviewResult, CodeReviewResultSummary

_EXPORT_MODULES = {
    "ArticleId": "bcbench.categories.code_review.entry",
    "CodeReviewEntry": "bcbench.categories.code_review.entry",
    "CodeReviewEntryMetadata": "bcbench.categories.code_review.entry",
    "CodeReviewPipeline": "bcbench.categories.code_review.pipeline",
    "CodeReviewResult": "bcbench.categories.code_review.results",
    "CodeReviewResultSummary": "bcbench.categories.code_review.results",
    "ReviewComment": "bcbench.categories.code_review.entry",
    "Severity": "bcbench.categories.code_review.entry",
    "build_definition": "bcbench.categories.code_review.definition",
}


def __getattr__(name: str) -> object:
    if module := _EXPORT_MODULES.get(name):
        return getattr(import_module(module), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ArticleId",
    "CodeReviewEntry",
    "CodeReviewEntryMetadata",
    "CodeReviewPipeline",
    "CodeReviewResult",
    "CodeReviewResultSummary",
    "ReviewComment",
    "Severity",
    "build_definition",
]
