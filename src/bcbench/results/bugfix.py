from typing import Self

from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.types import EvaluationContext


class BugFixResult(ExecutionBasedEvaluationResult):
    """Result class for bug-fix evaluation category."""

    generated_test_pre_patch_failed: bool = False
    generated_test_post_patch_passed: bool = False
    benchmark_test_passed: bool = False

    @property
    def category_metrics(self) -> dict[str, int | float | bool]:
        return {
            **super().category_metrics,
            "generated_test_pre_patch_failed": self.generated_test_pre_patch_failed,
            "generated_test_post_patch_passed": self.generated_test_post_patch_passed,
            "benchmark_test_passed": self.benchmark_test_passed,
        }

    @property
    def display_row(self) -> dict[str, str]:
        return {
            "Generated Test Failed Before Fix": "Yes" if self.generated_test_pre_patch_failed else "No",
            "Generated Test Passed After Fix": "Yes" if self.generated_test_post_patch_passed else "No",
            "Benchmark Test Passed": "Yes" if self.benchmark_test_passed else "No",
        }

    @classmethod
    def create_success(cls, context: "EvaluationContext", output: str) -> Self:
        return cls(
            **cls._base_fields(context),
            output=output,
            resolved=True,
            build=True,
            generated_test_pre_patch_failed=True,
            generated_test_post_patch_passed=True,
            benchmark_test_passed=True,
        )

    @classmethod
    def create_verification_failure(
        cls,
        context: "EvaluationContext",
        output: str,
        error_message: str,
        *,
        build: bool,
        generated_test_pre_patch_failed: bool = False,
        generated_test_post_patch_passed: bool = False,
    ) -> Self:
        return cls(
            **cls._base_fields(context),
            output=output,
            error_message=error_message,
            resolved=False,
            build=build,
            generated_test_pre_patch_failed=generated_test_pre_patch_failed,
            generated_test_post_patch_passed=generated_test_post_patch_passed,
            benchmark_test_passed=False,
        )

    @classmethod
    def create_test_failure(cls, context: "EvaluationContext", output: str, error_message: str = "Tests failed") -> Self:
        return cls.create_verification_failure(context, output, error_message, build=True)
