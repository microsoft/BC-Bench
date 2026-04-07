from typing import Self

from bcbench.results.base import BaseEvaluationResult
from bcbench.types import EvaluationContext


class TestGenerationResult(BaseEvaluationResult):
    """Result class for test-generation evaluation category.

    Inherits all shared metrics from BaseEvaluationResult.
    Tracks whether generated tests failed before patch and passed after patch.
    """

    pre_patch_failed: bool = False
    post_patch_passed: bool = False

    @classmethod
    def create_no_tests_extracted(cls, context: "EvaluationContext", generated_patch: str, error_message: str) -> Self:
        return cls._create_from_context(context, resolved=False, build=False, generated_patch=generated_patch, error_message=error_message)
