from typing import Self

from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.types import EvaluationContext


class TestGenerationResult(ExecutionBasedEvaluationResult):
    """Result class for test-generation evaluation category."""

    pre_patch_failed: bool = False
    post_patch_passed: bool = False

    @property
    def category_metrics(self) -> dict[str, int | float | bool]:
        return {**super().category_metrics, "pre_patch_failed": self.pre_patch_failed, "post_patch_passed": self.post_patch_passed}

    @property
    def display_row(self) -> dict[str, str]:
        return {
            "Pre-Patch Failed": "Yes" if self.pre_patch_failed else "No",
            "Post-Patch Passed": "Yes" if self.post_patch_passed else "No",
        }

    @classmethod
    def create_no_tests_extracted(cls, context: "EvaluationContext", output: str, error_message: str) -> Self:
        return cls._create_from_context(context, resolved=False, build=False, output=output, error_message=error_message)
