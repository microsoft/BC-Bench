from typing import Self

from pydantic import BaseModel

from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.types import EvaluationContext


class TestCheckOutcome(BaseModel):
    """Outcome of validating the agent's generated test against the gold patch."""

    build: bool = False
    pre_patch_failed: bool = False
    post_patch_passed: bool = False
    error_message: str | None = None

    @property
    def correct(self) -> bool:
        return self.build and self.pre_patch_failed and self.post_patch_passed


class FixCheckOutcome(BaseModel):
    """Outcome of validating the agent's fix against the gold test patch."""

    build: bool = False
    passed: bool = False
    error_message: str | None = None

    @property
    def correct(self) -> bool:
        return self.build and self.passed


class BugFixResult(ExecutionBasedEvaluationResult):
    """Result class for bug-fix evaluation category."""

    test_build: bool = False
    pre_patch_failed: bool = False
    post_patch_passed: bool = False
    fix_build: bool = False
    fix_passed: bool = False

    @property
    def test_correct(self) -> bool:
        return self.test_build and self.pre_patch_failed and self.post_patch_passed

    @property
    def fix_correct(self) -> bool:
        return self.fix_build and self.fix_passed

    @property
    def category_metrics(self) -> dict[str, int | float | bool]:
        return {
            **super().category_metrics,
            "test_build": self.test_build,
            "pre_patch_failed": self.pre_patch_failed,
            "post_patch_passed": self.post_patch_passed,
            "fix_build": self.fix_build,
            "fix_passed": self.fix_passed,
            "test_correct": self.test_correct,
            "fix_correct": self.fix_correct,
        }

    @property
    def display_row(self) -> dict[str, str]:
        return {
            "Test Correct": "Yes" if self.test_correct else "No",
            "Fix Correct": "Yes" if self.fix_correct else "No",
        }

    @classmethod
    def from_outcomes(cls, context: "EvaluationContext", output: str, test_outcome: TestCheckOutcome, fix_outcome: FixCheckOutcome) -> Self:
        errors = [message for message in (test_outcome.error_message, fix_outcome.error_message) if message]

        return cls(
            **cls._base_fields(context),
            output=output,
            error_message="\n\n".join(errors) or None,
            resolved=test_outcome.correct and fix_outcome.correct,
            build=test_outcome.build and fix_outcome.build,
            test_build=test_outcome.build,
            pre_patch_failed=test_outcome.pre_patch_failed,
            post_patch_passed=test_outcome.post_patch_passed,
            fix_build=fix_outcome.build,
            fix_passed=fix_outcome.passed,
        )

    @classmethod
    def create_success(cls, context: "EvaluationContext", output: str) -> Self:
        return cls(
            **cls._base_fields(context),
            output=output,
            resolved=True,
            build=True,
            test_build=True,
            pre_patch_failed=True,
            post_patch_passed=True,
            fix_build=True,
            fix_passed=True,
        )

    @classmethod
    def create_test_failure(cls, context: "EvaluationContext", output: str, error_message: str = "Tests failed") -> Self:
        return cls(
            **cls._base_fields(context),
            output=output,
            error_message=error_message,
            resolved=False,
            build=True,
            test_build=True,
            fix_build=True,
        )
