"""Custom exceptions for BC-Bench operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bcbench.types import AgentMetrics, ExperimentConfiguration

__all__ = [
    "AgentError",
    "BCBenchError",
    "BuildError",
    "CollectionError",
    "CollectionError",
    "CollectionError",
    "ConfigurationError",
    "DatasetError",
    "EmptyDiffError",
    "EntryNotFoundError",
    "GitOperationError",
    "InvalidEntryFormatError",
    "NoEntriesFoundError",
    "PatchApplicationError",
    "TestExecutionError",
]


class BCBenchError(Exception):
    """Base exception for all BC-Bench operations."""


class DatasetError(BCBenchError):
    """Base class for dataset-related errors."""


class EntryNotFoundError(DatasetError):
    """Dataset entry not found."""

    def __init__(self, entry_id: str):
        self.entry_id = entry_id
        super().__init__(f"Entry with instance_id '{entry_id}' not found in dataset")


class InvalidEntryFormatError(DatasetError):
    """Invalid format in dataset entry."""

    def __init__(self, entry: str, details: str = ""):
        self.entry = entry
        self.details = details
        message = f"Invalid entry format: {entry}"
        if details:
            message += f" ({details})"
        super().__init__(message)


class NoEntriesFoundError(DatasetError):
    """No entries found matching the specified criteria."""

    def __init__(self, criteria: str = ""):
        self.criteria = criteria
        message = "No entries matched the filter criteria"
        if criteria:
            message = f"No entries found for {criteria}"
        super().__init__(message)


class GitOperationError(BCBenchError):
    """Base class for git operation failures."""


class PatchApplicationError(GitOperationError):
    """Failed to apply a patch."""

    def __init__(self, patch_name: str, stderr: str = ""):
        self.patch_name = patch_name
        self.stderr = stderr
        message = f"Failed to apply {patch_name}"
        if stderr:
            message += f": {stderr}"
        super().__init__(message)


class EmptyDiffError(GitOperationError):
    """Generated diff is empty."""

    def __init__(self):
        message = "Generated diff is empty. Agent did not make any changes."
        super().__init__(message)


class BuildError(BCBenchError):
    """Build or publish operation failures."""

    def __init__(self, project_path: str, stderr: str = ""):
        self.project_path = project_path
        self.stderr = stderr
        message = f"Build or publish failed for {project_path}"
        if stderr:
            message += f": {stderr}"
        super().__init__(message)


class BuildTimeoutExpired(BCBenchError):
    """Build and publish operation timed out."""

    def __init__(self, project_path: str, timeout: int):
        self.project_path = project_path
        self.timeout = timeout
        message = f"Build and publish timed out for {project_path} after {timeout} seconds"
        super().__init__(message)


class TestExecutionError(BCBenchError):
    """Test execution failures."""

    def __init__(self, expectation: str, stderr: str = ""):
        self.expectation = expectation
        self.stderr = stderr
        message = f"Test result did not meet expectation (expected: {expectation})"
        if stderr:
            message += f"\n{stderr}"
        super().__init__(message)


class TestExecutionTimeoutExpired(BCBenchError):
    """Test execution timed out."""

    def __init__(self, tests: str, timeout: int):
        self.tests = tests
        self.timeout = timeout
        message = f"Test execution timed out (tests: {tests}) after {timeout} seconds"
        super().__init__(message)


class NoTestsExtractedError(BCBenchError):
    """No tests extracted from the generated patch."""

    def __init__(self):
        message = "No tests extracted from the generated patch."
        super().__init__(message)


class AgentError(BCBenchError):
    """Agent execution errors."""


class AgentTimeoutError(BCBenchError):
    """Agent execution timeout errors."""

    def __init__(self, message: str, metrics: AgentMetrics | None = None, config: ExperimentConfiguration | None = None):
        self.metrics = metrics
        self.config = config
        super().__init__(message)


class ConfigurationError(BCBenchError):
    """Configuration-related errors."""


class CollectionError(BCBenchError):
    """Dataset collection related errors. Note: Collection is WIP with hardcoded values."""

    def __init__(self, message: str):
        message = f"Collection error (Note: Collection is WIP with hardcoded values): {message}"
        super().__init__(message)
