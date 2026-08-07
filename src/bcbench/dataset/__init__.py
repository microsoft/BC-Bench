"""Dataset module for querying, validating and analyze dataset entries."""

from bcbench.dataset.codereview import CodeReviewEntry, ReviewComment, Severity
from bcbench.dataset.coverage import (
    ArticleCoverage,
    CoverageReport,
    build_coverage_report,
    collect_declared_articles,
    enumerate_inventory,
    resolve_bcquality_root,
)
from bcbench.dataset.dataset_entry import BaseDatasetEntry, BugFixEntry, NL2ALEntry, RepoGroundedEntry, TestEntry, TestGenEntry

__all__ = [
    "ArticleCoverage",
    "BaseDatasetEntry",
    "BugFixEntry",
    "CodeReviewEntry",
    "CoverageReport",
    "NL2ALEntry",
    "RepoGroundedEntry",
    "ReviewComment",
    "Severity",
    "TestEntry",
    "TestGenEntry",
    "build_coverage_report",
    "collect_declared_articles",
    "enumerate_inventory",
    "resolve_bcquality_root",
]
