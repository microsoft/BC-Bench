from typing import Self

from bcbench.dataset import BaseDatasetEntry
from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.types import EvaluationContext


class BugFixResult(ExecutionBasedEvaluationResult):
    """Result class for bug-fix evaluation category."""

    @classmethod
    def create_test_failure[E: BaseDatasetEntry](cls, context: EvaluationContext[E], output: str, error_message: str = "Tests failed") -> Self:
        return cls(**cls._base_fields(context), output=output, error_message=error_message, resolved=False, build=True)
