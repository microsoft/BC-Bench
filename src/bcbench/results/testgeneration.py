from bcbench.results.base import BaseEvaluationResult, T
from bcbench.types import EvaluationContext


class TestGenerationResult(BaseEvaluationResult):
    """Result class for test-generation evaluation category.

    Inherits all shared metrics from BaseEvaluationResult.
    Tracks whether generated tests failed before patch and passed after patch.
    """

    pre_patch_failed: bool | None = None
    post_patch_passed: bool | None = None

    @classmethod
    def create_no_tests_extracted(cls: type[T], context: "EvaluationContext", generated_patch: str, error_message: str) -> T:
        return cls._create_from_context(context, resolved=False, build=False, generated_patch=generated_patch, error_message=error_message)
