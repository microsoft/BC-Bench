from collections.abc import Sequence
from typing import Self

from pydantic import Field

from bcbench.dataset import ReviewComment
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.metrics import f1_score, f_beta_score, precision_recall
from bcbench.results.summary import EvaluationResultSummary
from bcbench.types import EvaluationContext


def _resolve_domain(context: "EvaluationContext") -> str:
    entry = context.entry
    domain = getattr(entry, "domain", None) or entry.metadata.area
    return domain if isinstance(domain, str) and domain else "unknown"


def _with_comment_domains(generated_comments: list[ReviewComment], domain: str) -> list[ReviewComment]:
    """Stamp the entry domain onto comments that have no explicit domain. All comments are kept."""
    return [comment if comment.domain else comment.model_copy(update={"domain": domain}) for comment in generated_comments]


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").lstrip("/")


def _line_distance(line: int, start: int, end: int | None) -> int:
    effective_end = end if end is not None else start
    if start <= line <= effective_end:
        return 0
    if line < start:
        return start - line
    return line - effective_end


def match_comments(
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

    domain: str = "unknown"
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
    f_beta_05: float = Field(default=0.0, ge=0.0, le=1.0)
    f_beta_2: float = Field(default=0.0, ge=0.0, le=1.0)
    severity_mae: float = 0.0

    @classmethod
    def create(
        cls,
        context: "EvaluationContext",
        output: str,
        expected_comments: list[ReviewComment],
        generated_comments: list[ReviewComment],
        line_tolerance: int,
        matched_pairs: list[tuple[ReviewComment, ReviewComment]] | None = None,
    ) -> Self:
        domain = _resolve_domain(context)
        generated_comments = _with_comment_domains(generated_comments, domain)
        if matched_pairs is None:
            matched_pairs = match_comments(expected_comments, generated_comments, line_tolerance)
        matched_count = len(matched_pairs)
        precision, recall = precision_recall(matched_count, len(generated_comments), len(expected_comments))

        return cls(
            **cls._base_fields(context),
            domain=domain,
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
            f_beta_05=f_beta_score(precision, recall, beta=0.5),
            f_beta_2=f_beta_score(precision, recall, beta=2.0),
            severity_mae=_severity_mae(matched_pairs),
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
            domain=_resolve_domain(context),
            output=output,
            expected_comments=expected_comments,
            line_tolerance=0,
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
            "f_beta_05": round(self.f_beta_05, 3),
            "f_beta_2": round(self.f_beta_2, 3),
            "severity_mae": round(self.severity_mae, 3),
            "valid_review_output": self.valid_review_output,
        }

    @property
    def display_row(self) -> dict[str, str]:
        return {
            "Domain": self.domain,
            "Generated": str(len(self.generated_comments)),
            "Matched": str(self.matched_comment_count),
            "Expected": str(len(self.expected_comments)),
            "Precision": f"{self.precision:.2f}",
            "Recall": f"{self.recall:.2f}",
            "F1": f"{self.f1:.2f}",
        }


class CodeReviewResultSummary(EvaluationResultSummary):
    """
    Summary for the code-review category.

    Micro metrics aggregate matched/expected/generated comment counts across all results (volume-weighted).
    Macro metrics average per-task scores (each task weighted equally).
    """

    generated_comment_count: int = Field(default=0, ge=0)
    expected_comment_count: int = Field(default=0, ge=0)
    matched_comment_count: int = Field(default=0, ge=0)
    incorrect_comment_count: int = Field(default=0, ge=0)
    missed_comment_count: int = Field(default=0, ge=0)

    precision: float = Field(default=0.0, ge=0.0, le=1.0)
    recall: float = Field(default=0.0, ge=0.0, le=1.0)
    f1: float = Field(default=0.0, ge=0.0, le=1.0)
    f_beta_05: float = Field(default=0.0, ge=0.0, le=1.0)
    f_beta_2: float = Field(default=0.0, ge=0.0, le=1.0)

    macro_precision: float = Field(default=0.0, ge=0.0, le=1.0)
    macro_recall: float = Field(default=0.0, ge=0.0, le=1.0)
    macro_f1: float = Field(default=0.0, ge=0.0, le=1.0)
    macro_f_beta_05: float = Field(default=0.0, ge=0.0, le=1.0)
    macro_f_beta_2: float = Field(default=0.0, ge=0.0, le=1.0)

    severity_mae: float = 0.0
    valid_review_output_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    def display_summary(self) -> dict[str, int | float]:
        return {
            "generated_comment_count": self.generated_comment_count,
            "expected_comment_count": self.expected_comment_count,
            "matched_comment_count": self.matched_comment_count,
            "incorrect_comment_count": self.incorrect_comment_count,
            "missed_comment_count": self.missed_comment_count,
            "micro_precision": round(self.precision * 100, 1),
            "micro_recall": round(self.recall * 100, 1),
            "micro_f1": round(self.f1 * 100, 1),
            "micro_f_beta_05": round(self.f_beta_05 * 100, 1),
            "micro_f_beta_2": round(self.f_beta_2 * 100, 1),
            "macro_precision": round(self.macro_precision * 100, 1),
            "macro_recall": round(self.macro_recall * 100, 1),
            "macro_f1": round(self.macro_f1 * 100, 1),
            "macro_f_beta_05": round(self.macro_f_beta_05 * 100, 1),
            "macro_f_beta_2": round(self.macro_f_beta_2 * 100, 1),
            "severity_mae": round(self.severity_mae, 3),
            "valid_review_output_rate": round(self.valid_review_output_rate * 100, 1),
        }

    @classmethod
    def from_results(cls, results: Sequence[BaseEvaluationResult], run_id: str) -> "CodeReviewResultSummary":
        summary = super().from_results(results, run_id)
        assert isinstance(summary, CodeReviewResultSummary)

        code_review_results: list[CodeReviewResult] = [r for r in results if isinstance(r, CodeReviewResult)]
        total_results: int = len(code_review_results)

        generated_total: int = sum(len(r.generated_comments) for r in code_review_results)
        expected_total: int = sum(len(r.expected_comments) for r in code_review_results)
        matched_total: int = sum(r.matched_comment_count for r in code_review_results)
        incorrect_total: int = sum(r.incorrect_comment_count for r in code_review_results)
        missed_total: int = sum(r.missed_comment_count for r in code_review_results)

        precision, recall = precision_recall(matched_total, generated_total, expected_total)
        f1: float = f1_score(precision, recall)
        f_beta_05: float = f_beta_score(precision, recall, beta=0.5)
        f_beta_2: float = f_beta_score(precision, recall, beta=2.0)

        macro_precision: float = sum(r.precision for r in code_review_results) / total_results
        macro_recall: float = sum(r.recall for r in code_review_results) / total_results
        macro_f1: float = sum(r.f1 for r in code_review_results) / total_results
        macro_f_beta_05: float = sum(r.f_beta_05 for r in code_review_results) / total_results
        macro_f_beta_2: float = sum(r.f_beta_2 for r in code_review_results) / total_results

        weighted_mae_numerator: float = sum(r.severity_mae * r.matched_comment_count for r in code_review_results)
        weighted_mae_denominator: int = sum(r.matched_comment_count for r in code_review_results)
        severity_mae: float = weighted_mae_numerator / weighted_mae_denominator if weighted_mae_denominator > 0 else 0.0

        valid_output_count: int = sum(1 for r in code_review_results if r.valid_review_output)
        valid_output_rate: float = valid_output_count / total_results

        return summary.model_copy(
            update={
                "generated_comment_count": generated_total,
                "expected_comment_count": expected_total,
                "matched_comment_count": matched_total,
                "incorrect_comment_count": incorrect_total,
                "missed_comment_count": missed_total,
                "precision": round(precision, 3),
                "recall": round(recall, 3),
                "f1": round(f1, 3),
                "f_beta_05": round(f_beta_05, 3),
                "f_beta_2": round(f_beta_2, 3),
                "macro_precision": round(macro_precision, 3),
                "macro_recall": round(macro_recall, 3),
                "macro_f1": round(macro_f1, 3),
                "macro_f_beta_05": round(macro_f_beta_05, 3),
                "macro_f_beta_2": round(macro_f_beta_2, 3),
                "severity_mae": round(severity_mae, 3),
                "valid_review_output_rate": round(valid_output_rate, 3),
            }
        )
