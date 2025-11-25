from bcbench.results.base import BaseEvaluationResult


class TestGenerationResult(BaseEvaluationResult):
    """Result class for test-generation evaluation category.

    Inherits all shared metrics from BaseEvaluationResult.
    Tracks whether generated tests failed before patch and passed after patch.
    """

    pre_patch_failed: bool | None = None
    post_patch_passed: bool | None = None
