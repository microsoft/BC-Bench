"""Custom exceptions for BC-Bench operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bcbench.types import AgentMetrics, ExperimentConfiguration

__all__ = [
    "AgentError",
    "AgentInfrastructureError",
    "BCBenchError",
    "CollectionError",
    "ConfigurationError",
    "DatasetError",
    "EmptyGoldResultError",
    "EntryNotFoundError",
    "InvalidEntryFormatError",
    "NoEntriesFoundError",
]


class BCBenchError(Exception):
    """Base exception for all BC-Bench operations."""


class DatasetError(BCBenchError):
    """Base class for dataset-related errors."""


class EntryNotFoundError(DatasetError):
    """Dataset entry not found."""

    def __init__(self, entry_id: str) -> None:
        self.entry_id = entry_id
        super().__init__(f"Entry with instance_id '{entry_id}' not found in dataset")


class InvalidEntryFormatError(DatasetError):
    """Invalid format in dataset entry."""

    def __init__(self, entry: str, details: str = "") -> None:
        self.entry = entry
        self.details = details
        message = f"Invalid entry format: {entry}"
        if details:
            message += f" ({details})"
        super().__init__(message)


class NoEntriesFoundError(DatasetError):
    """No entries found matching the specified criteria."""

    def __init__(self, criteria: str = "") -> None:
        self.criteria = criteria
        message = "No entries matched the filter criteria"
        if criteria:
            message = f"No entries found for {criteria}"
        super().__init__(message)


class EmptyGoldResultError(BCBenchError):
    """A data-query gold query returned zero rows.

    Every data-query question is an aggregation with a determinate, non-empty answer, so an empty gold
    means the harness/environment is broken (BC cold-start/degraded, wrong company, or a bad gold
    query) — never a legitimate expected result. It must fail loudly: otherwise an agent that
    retrieved nothing (empty answer.json) would spuriously match an empty gold and score as resolved.
    """

    def __init__(self, instance_id: str) -> None:
        self.instance_id = instance_id
        message = (
            f"Gold query for {instance_id} returned 0 rows. A data-query gold must be non-empty; an "
            "empty result indicates a harness/environment problem (degraded BC container, wrong "
            "BC_COMPANY, or a broken gold_query), not a valid expected answer."
        )
        super().__init__(message)


class NoTestsExtractedError(BCBenchError):
    """No tests extracted from the generated patch."""

    def __init__(self) -> None:
        message = "No tests extracted from the generated patch."
        super().__init__(message)


class AgentError(BCBenchError):
    """Agent execution errors."""


class AgentInfrastructureError(AgentError):
    """A dependency failure that prevented the agent from producing an evaluable result."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        metrics: AgentMetrics | None = None,
        config: ExperimentConfiguration | None = None,
    ) -> None:
        self.provider = provider
        self.status_code = status_code
        self.metrics = metrics
        self.config = config
        super().__init__(message)


class AgentTimeoutError(BCBenchError):
    """Agent execution timeout errors."""

    def __init__(self, message: str, metrics: AgentMetrics | None = None, config: ExperimentConfiguration | None = None) -> None:
        self.metrics = metrics
        self.config = config
        super().__init__(message)


class ConfigurationError(BCBenchError):
    """Configuration-related errors."""


class CollectionError(BCBenchError):
    """Dataset collection related errors. Note: Collection is WIP with hardcoded values."""

    def __init__(self, message: str) -> None:
        message = f"Collection error (Note: Collection is WIP with hardcoded values): {message}"
        super().__init__(message)


class LLMJudgeError(BCBenchError):
    """LLM judge related errors."""
