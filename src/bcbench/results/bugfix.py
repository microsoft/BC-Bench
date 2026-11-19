from typing import Self

from bcbench_core.agent.harness import AgentResult

from bcbench.dataset import BaseDatasetEntry
from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.types import EvaluationContext


class BugFixResult(ExecutionBasedEvaluationResult):
    """Result class for bug-fix evaluation category."""

    @classmethod
    def create_test_failure[E: BaseDatasetEntry](cls, context: EvaluationContext[E], agent_result: AgentResult, output: str, error_message: str = "Tests failed") -> Self:
        return cls(**cls._base_fields(context, agent_result), output=output, error_message=error_message, resolved=False, build=True)
