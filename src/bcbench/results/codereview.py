from typing import Self

from pydantic import Field, model_validator

from bcbench.dataset.codereview import ReviewComment
from bcbench.logger import get_logger
from bcbench.results.base import BaseEvaluationResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["CodeReviewResult"]


def _parse_review_output(raw_output: str) -> list[ReviewComment]:
    """Parse raw JSON output into ReviewComment objects.

    NOTE: This is a minimal parser for the POC. The owning team should make this more robust.
    """
    import json

    if not raw_output.strip():
        return []

    try:
        raw = json.loads(raw_output)
    except json.JSONDecodeError:
        logger.warning("Failed to parse review output as JSON")
        return []

    if not isinstance(raw, list):
        logger.warning(f"Expected JSON array in review output, got {type(raw).__name__}")
        return []

    comments: list[ReviewComment] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            comments.append(ReviewComment.model_validate(item))
        except Exception:
            logger.debug(f"Skipping malformed comment: {item}")
    return comments


class CodeReviewResult(BaseEvaluationResult):
    """
    Result for the code-review category.

    TODO: Code Review team should implement the real metrics here. This is just a placeholder to demo.
    """

    generated_comments: list[ReviewComment] = Field(default_factory=list)

    @model_validator(mode="after")
    def _parse_comments_from_output(self) -> Self:
        if not self.generated_comments and self.output:
            object.__setattr__(self, "generated_comments", _parse_review_output(self.output))
        return self

    @classmethod
    def create_success(
        cls,
        context: "EvaluationContext",
        output: str,
    ) -> Self:
        return cls(**cls._base_fields(context), output=output)

    @property
    def category_metrics(self) -> dict[str, int | float | bool]:
        return {
            "generated_comment_count": len(self.generated_comments),
        }

    @property
    def display_row(self) -> dict[str, str]:
        return {
            "Comments": str(len(self.generated_comments)),
        }
