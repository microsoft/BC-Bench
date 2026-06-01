from typing import Self

from pydantic import Field

from bcbench.dataset.codereview import ReviewComment
from bcbench.logger import get_logger
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.metrics import f1_score, precision_recall
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["CodeReviewResult"]


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").lstrip("/")


def _line_distance(line: int, start: int, end: int | None) -> int:
    effective_end = end if end is not None else start
    if start <= line <= effective_end:
        return 0
    if line < start:
        return start - line
    return line - effective_end


def _match_comments(
    expected_comments: list[ReviewComment],
    generated_comments: list[ReviewComment],
    line_tolerance: int,
) -> list[tuple[ReviewComment, ReviewComment]]:
    """Greedily pair each expected comment with the nearest unused generated comment in the same file."""
    matched: list[tuple[ReviewComment, ReviewComment]] = []
    used_generated: set[int] = set()

    for expected in expected_comments:
        expected_file = _normalize_path(expected.file)
        best_index: int | None = None
        best_distance: int | None = None

        for index, generated in enumerate(generated_comments):
            if index in used_generated or _normalize_path(generated.file) != expected_file:
                continue

            distance: int = _line_distance(generated.line_start, expected.line_start, expected.line_end)
            if distance > line_tolerance:
                continue

            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_index = index

        if best_index is not None:
            used_generated.add(best_index)
            matched.append((expected, generated_comments[best_index]))

    return matched


def _severity_mae(matched_pairs: list[tuple[ReviewComment, ReviewComment]]) -> float:
    if not matched_pairs:
        return 0.0
    total_error: int = sum(abs(expected.severity.level - generated.severity.level) for expected, generated in matched_pairs)
    return total_error / len(matched_pairs)


class CodeReviewResult(BaseEvaluationResult):
    """Result for the code-review category."""

    generated_comments: list[ReviewComment] = Field(default_factory=list)
    expected_comments: list[ReviewComment] = Field(default_factory=list)
    line_tolerance: int = Field(ge=0)

    valid_review_output: bool = False
    matched_comment_count: int = Field(default=0, ge=0)
    missed_comment_count: int = Field(default=0, ge=0)
    incorrect_comment_count: int = Field(default=0, ge=0)

    precision: float = Field(default=0.0, ge=0.0, le=1.0)
    recall: float = Field(default=0.0, ge=0.0, le=1.0)
    f1: float = Field(default=0.0, ge=0.0, le=1.0)
    severity_mae: float = 0.0

    @classmethod
    def create(
        cls,
        context: "EvaluationContext",
        output: str,
        expected_comments: list[ReviewComment],
        generated_comments: list[ReviewComment],
        line_tolerance: int,
    ) -> Self:
        matches = _match_comments(expected_comments, generated_comments, line_tolerance)
        matched_count = len(matches)
        precision, recall = precision_recall(matched_count, len(generated_comments), len(expected_comments))

        return cls(
            **cls._base_fields(context),
            output=output,
            expected_comments=expected_comments,
            generated_comments=generated_comments,
            line_tolerance=line_tolerance,
            valid_review_output=True,
            matched_comment_count=matched_count,
            incorrect_comment_count=max(0, len(generated_comments) - matched_count),
            missed_comment_count=max(0, len(expected_comments) - matched_count),
            precision=precision,
            recall=recall,
            f1=f1_score(precision, recall),
            severity_mae=_severity_mae(matches),
        )

    @classmethod
    def create_invalid(
        cls,
        context: "EvaluationContext",
        output: str,
        expected_comments: list[ReviewComment],
    ) -> Self:
        """Result for output that could not be parsed into a review — scored zero."""
        return cls(
            **cls._base_fields(context),
            output=output,
            expected_comments=expected_comments,
            valid_review_output=False,
        )

    @property
    def category_metrics(self) -> dict[str, int | float | bool]:
        return {
            "generated_comment_count": len(self.generated_comments),
            "expected_comment_count": len(self.expected_comments),
            "matched_comment_count": self.matched_comment_count,
            "incorrect_comment_count": self.incorrect_comment_count,
            "missed_comment_count": self.missed_comment_count,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
            "severity_mae": round(self.severity_mae, 3),
            "valid_review_output": self.valid_review_output,
        }

    @property
    def display_row(self) -> dict[str, str]:
        return {
            "Generated": str(len(self.generated_comments)),
            "Matched": str(self.matched_comment_count),
            "Expected": str(len(self.expected_comments)),
            "Precision": f"{self.precision:.2f}",
            "Recall": f"{self.recall:.2f}",
            "F1": f"{self.f1:.2f}",
        }
