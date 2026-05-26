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
    def create_success(cls, context: "EvaluationContext", output: str) -> Self:
        return cls(**cls._base_fields(context), output=output, resolved=True, build=True, pre_patch_failed=True, post_patch_passed=True)

    @classmethod
    def create_pre_patch_failure(cls, context: "EvaluationContext", output: str, error_message: str) -> Self:
        return cls(
            **cls._base_fields(context),
            output=output,
            error_message=error_message,
            resolved=False,
            build=True,
            pre_patch_failed=False,
            post_patch_passed=False,
        )

    @classmethod
    def create_post_patch_failure(cls, context: "EvaluationContext", output: str, error_message: str) -> Self:
        return cls(
            **cls._base_fields(context),
            output=output,
            error_message=error_message,
            resolved=False,
            build=True,
            pre_patch_failed=True,
            post_patch_passed=False,
        )

    @classmethod
    def create_no_tests_extracted(cls, context: "EvaluationContext", output: str, error_message: str) -> Self:
        return cls(**cls._base_fields(context), output=output, error_message=error_message, resolved=False, build=False)
