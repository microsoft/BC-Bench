"""Custom exceptions for BC-Bench operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bcbench.operations.test_execution import TestRunSummary
    from bcbench.types import AgentMetrics, ExperimentConfiguration

__all__ = [
    "AgentError",
    "BCBenchError",
    "BuildError",
    "CollectionError",
    "ConfigurationError",
    "DatasetError",
    "EmptyDiffError",
    "EmptyGoldResultError",
    "EntryNotFoundError",
    "GeneratedOutputError",
    "GitOperationError",
    "InvalidEntryFormatError",
    "NoEntriesFoundError",
    "PatchApplicationError",
    "ProjectDiscoveryError",
    "TestExecutionError",
    "TestInfrastructureError",
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


class GitOperationError(BCBenchError):
    """Base class for git operation failures."""


class PatchApplicationError(GitOperationError):
    """Failed to apply a patch."""

    def __init__(self, patch_name: str, stderr: str = "") -> None:
        self.patch_name = patch_name
        self.stderr = stderr
        message = f"Failed to apply {patch_name}"
        if stderr:
            message += f": {stderr}"
        super().__init__(message)


class EmptyDiffError(GitOperationError):
    """Generated diff is empty."""

    def __init__(self) -> None:
        message = "Generated diff is empty. Agent did not make any changes."
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


def _extract_compiler_errors(output: str, max_lines: int = 30) -> str:
    """Extract AL compiler error/warning lines from build output."""
    if not output:
        return ""

    lines = output.splitlines()
    # Match lines like: path.al(line,col): error AL0185: ...
    error_lines = [line for line in lines if ": error " in line or ": warning " in line]

    if error_lines:
        return "\n".join(error_lines[:max_lines])

    # Fallback: return last N lines if no error pattern found
    return "\n".join(lines[-max_lines:])


def _bounded_output(lines: list[str], max_lines: int, max_chars: int = 4000) -> str:
    return "\n".join(lines[:max_lines])[:max_chars]


def _extract_test_errors(output: str, max_lines: int = 20) -> str:
    """Extract test failure information from test output, filtering verbose lines."""
    if not output:
        return ""

    skip_patterns = (
        "BcContainerHelper",
        "BC.HelperFunctions",
        "Running on Windows",
        "Using Container",
        "WARNING: TaskScheduler",
        "Connecting to http://",
        "Tests failed for",
        "::group::",
        "::endgroup::",
        "::error",
        "::warning",
        "Running tests for Codeunit",
    )

    def is_relevant(line: str) -> bool:
        return not any(skip in line for skip in skip_patterns)

    lines = output.splitlines()
    filtered = list(filter(is_relevant, lines))

    if filtered:
        failure_index = next(
            (index for index, line in enumerate(filtered) if "Testfunction " in line and " Failure" in line),
            None,
        )
        if failure_index is not None:
            return _bounded_output(filtered[max(0, failure_index - 1) :], max_lines)
        return _bounded_output(filtered, max_lines)

    # Fallback: return last N lines if no pattern found
    return _bounded_output(lines[-max_lines:], max_lines)


class BuildError(BCBenchError):
    """Build or publish operation failures."""

    def __init__(self, project_path: str, output: str = "") -> None:
        self.project_path = project_path
        self.output = output
        self.errors = _extract_compiler_errors(output)
        message = f"Build or publish failed for {project_path}:\n{self.errors}"

        super().__init__(message)


class BuildTimeoutExpired(BCBenchError):
    """Build and publish operation timed out."""

    def __init__(self, project_path: str, timeout: int) -> None:
        self.project_path = project_path
        self.timeout = timeout
        message = f"Build and publish timed out for {project_path} after {timeout} seconds"
        super().__init__(message)


class TestExecutionError(BCBenchError):
    """Test execution failures."""

    def __init__(
        self,
        expectation: str,
        stderr: str = "",
        stdout: str = "",
        reason: str = "",
        summary: TestRunSummary | None = None,
    ) -> None:
        self.expectation = expectation
        self.stderr = stderr
        self.stdout = stdout
        self.reason = reason
        self.summary = summary
        self.errors = _extract_test_errors(stdout)
        super().__init__(self.diagnostic_message)

    @property
    def diagnostic_message(self) -> str:
        message = f"Test result did not meet expectation (expected: {self.expectation})"
        if self.reason:
            message += f": {self.reason}"
        if self.errors:
            message += f"\nTest output:\n{self.errors}"
        stderr = _bounded_output(self.stderr.strip().splitlines(), max_lines=20)
        if stderr:
            message += f"\nStandard error:\n{stderr}"
        return message


class TestInfrastructureError(BCBenchError):
    """Business Central test infrastructure failed."""

    def __init__(
        self,
        expectation: str,
        reason: str,
        stdout: str = "",
        stderr: str = "",
        summary: TestRunSummary | None = None,
    ) -> None:
        self.expectation = expectation
        self.reason = reason
        self.stdout = stdout
        self.stderr = stderr
        self.summary = summary
        self.errors = _extract_test_errors(stdout)

        message = f"Test infrastructure failed (expected: {expectation}): {reason}"
        if self.errors:
            message += f"\nTest output:\n{self.errors}"
        if stderr.strip():
            message += f"\nStandard error:\n{stderr.strip()}"
        super().__init__(message)


class TestExecutionTimeoutExpired(BCBenchError):
    """Test execution timed out."""

    def __init__(self, tests: str, timeout: int) -> None:
        self.tests = tests
        self.timeout = timeout
        message = f"Test execution timed out (tests: {tests}) after {timeout} seconds"
        super().__init__(message)


class NoTestsExtractedError(BCBenchError):
    """No tests extracted from the generated patch."""

    def __init__(self) -> None:
        message = "No tests extracted from the generated patch."
        super().__init__(message)


class GeneratedOutputError(BCBenchError):
    """Agent-generated output is invalid."""


class AgentError(BCBenchError):
    """Agent execution errors."""


class AgentTimeoutError(BCBenchError):
    """Agent execution timeout errors."""

    def __init__(self, message: str, metrics: AgentMetrics | None = None, config: ExperimentConfiguration | None = None) -> None:
        self.metrics = metrics
        self.config = config
        super().__init__(message)


class ConfigurationError(BCBenchError):
    """Configuration-related errors."""


class ProjectDiscoveryError(BCBenchError):
    """AL project ownership discovery failed."""


class CollectionError(BCBenchError):
    """Dataset collection related errors. Note: Collection is WIP with hardcoded values."""

    def __init__(self, message: str) -> None:
        message = f"Collection error (Note: Collection is WIP with hardcoded values): {message}"
        super().__init__(message)


class LLMJudgeError(BCBenchError):
    """LLM judge related errors."""
