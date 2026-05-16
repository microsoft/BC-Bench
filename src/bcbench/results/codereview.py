import json
import re
from typing import Any, Self

from pydantic import Field, model_validator

from bcbench.dataset.codereview import ReviewComment
from bcbench.logger import get_logger
from bcbench.results.base import BaseEvaluationResult
from bcbench.types import EvaluationContext

logger = get_logger(__name__)

__all__ = ["CodeReviewResult"]


SEVERITY_LEVELS: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}

SEVERITY_ALIASES: dict[str, str] = {
    "error": "high",
    "warning": "medium",
    "suggestion": "low",
    "info": "low",
}


def _extract_json_candidate(raw_output: str) -> str:
    stripped = raw_output.strip()
    if not stripped:
        return ""

    if stripped.startswith("[") or stripped.startswith("{"):
        return stripped

    block_match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_output, re.IGNORECASE)
    if block_match:
        return block_match.group(1).strip()

    generic_block_match = re.search(r"```\s*([\s\S]*?)\s*```", raw_output)
    if generic_block_match:
        return generic_block_match.group(1).strip()

    return stripped


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").lstrip("/")


def _normalize_severity(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in SEVERITY_LEVELS:
        return normalized
    return SEVERITY_ALIASES.get(normalized, "medium")


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _normalize_comment(item: dict[str, Any]) -> ReviewComment | None:
    file_path = item.get("file") or item.get("filePath") or item.get("path")
    line_start = _to_int(item.get("line_start") or item.get("lineNumber") or item.get("line"))
    line_end = _to_int(item.get("line_end") or item.get("lineEnd") or item.get("endLine"))
    body = item.get("body") or item.get("issue") or item.get("comment")
    severity = _normalize_severity(str(item.get("severity", "medium")))

    if not isinstance(file_path, str) or not file_path.strip():
        return None
    if line_start is None:
        return None
    if not isinstance(body, str) or not body.strip():
        return None

    try:
        return ReviewComment(
            file=file_path.strip(),
            line_start=line_start,
            line_end=line_end,
            body=body.strip(),
            severity=severity,
        )
    except Exception:
        return None


def _parse_review_output(raw_output: str) -> tuple[list[ReviewComment], bool]:
    if not raw_output.strip():
        return [], False

    candidate = _extract_json_candidate(raw_output)
    if not candidate:
        return [], False

    try:
        raw = json.loads(candidate)
    except json.JSONDecodeError:
        logger.warning("Failed to parse review output as JSON")
        return [], False

    raw_items: Any
    if isinstance(raw, list):
        raw_items = raw
    elif isinstance(raw, dict) and isinstance(raw.get("findings"), list):
        raw_items = raw["findings"]
    else:
        logger.warning(f"Expected JSON array or object with findings[], got {type(raw).__name__}")
        return [], False

    comments: list[ReviewComment] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_comment(item)
        if normalized is not None:
            comments.append(normalized)
        else:
            logger.debug(f"Skipping malformed comment: {item}")

    return comments, True


def _line_distance(line: int, start: int, end: int | None) -> int:
    effective_end = end if end is not None else start
    if start <= line <= effective_end:
        return 0
    if line < start:
        return start - line
    return line - effective_end


def _severity_level(value: str) -> int:
    return SEVERITY_LEVELS[_normalize_severity(value)]


def _match_comments(
    expected_comments: list[ReviewComment],
    generated_comments: list[ReviewComment],
    line_tolerance: int,
) -> list[tuple[int, int]]:
    matched: list[tuple[int, int]] = []
    used_generated: set[int] = set()

    for expected_index, expected in enumerate(expected_comments):
        expected_file = _normalize_path(expected.file)
        best_generated_index: int | None = None
        best_distance: int | None = None

        for generated_index, generated in enumerate(generated_comments):
            if generated_index in used_generated:
                continue
            if _normalize_path(generated.file) != expected_file:
                continue

            distance = _line_distance(generated.line_start, expected.line_start, expected.line_end)
            if distance > line_tolerance:
                continue

            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_generated_index = generated_index

        if best_generated_index is not None:
            used_generated.add(best_generated_index)
            matched.append((expected_index, best_generated_index))

    return matched


def _compute_f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _compute_severity_mae(
    matched_pairs: list[tuple[int, int]],
    expected_comments: list[ReviewComment],
    generated_comments: list[ReviewComment],
) -> float:
    if not matched_pairs:
        return 0.0

    total_error = 0.0
    for expected_index, generated_index in matched_pairs:
        expected_level = _severity_level(expected_comments[expected_index].severity)
        generated_level = _severity_level(generated_comments[generated_index].severity)
        total_error += abs(expected_level - generated_level)

    return total_error / len(matched_pairs)


class CodeReviewResult(BaseEvaluationResult):
    """Result for the code-review category."""

    generated_comments: list[ReviewComment] = Field(default_factory=list)
    expected_comments: list[ReviewComment] = Field(default_factory=list)
    line_tolerance: int = 5

    valid_review_output: bool = False
    matched_comment_count: int = 0
    missed_comment_count: int = 0
    incorrect_comment_count: int = 0

    precision: float = 1.0
    recall: float = 1.0
    f1: float = 1.0
    severity_mae: float = 0.0

    @model_validator(mode="after")
    def _parse_comments_from_output(self) -> Self:
        if not self.generated_comments and self.output:
            parsed_comments, valid_output = _parse_review_output(self.output)
            object.__setattr__(self, "generated_comments", parsed_comments)
            object.__setattr__(self, "valid_review_output", valid_output)
        elif not self.output.strip():
            object.__setattr__(self, "valid_review_output", False)

        matches = _match_comments(self.expected_comments, self.generated_comments, self.line_tolerance)
        matched_count = len(matches)
        incorrect_count = max(0, len(self.generated_comments) - matched_count)
        missed_count = max(0, len(self.expected_comments) - matched_count)

        precision = matched_count / len(self.generated_comments) if self.generated_comments else 1.0
        recall = matched_count / len(self.expected_comments) if self.expected_comments else 1.0
        f1 = _compute_f1(precision, recall)
        severity_mae = _compute_severity_mae(matches, self.expected_comments, self.generated_comments)

        object.__setattr__(self, "matched_comment_count", matched_count)
        object.__setattr__(self, "incorrect_comment_count", incorrect_count)
        object.__setattr__(self, "missed_comment_count", missed_count)
        object.__setattr__(self, "precision", precision)
        object.__setattr__(self, "recall", recall)
        object.__setattr__(self, "f1", f1)
        object.__setattr__(self, "severity_mae", severity_mae)
        return self

    @classmethod
    def create_success(
        cls,
        context: "EvaluationContext",
        output: str,
        expected_comments: list[ReviewComment] | None = None,
        line_tolerance: int = 5,
    ) -> Self:
        return cls(
            **cls._base_fields(context),
            output=output,
            expected_comments=expected_comments or [],
            line_tolerance=line_tolerance,
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
            "Comments": f"{len(self.generated_comments)} ({self.matched_comment_count}/{len(self.expected_comments)} matched)",
            "F1": f"{self.f1:.2f}",
        }
