from typing import Self

from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.types import EvaluationContext


class ExtTriageResult(ExecutionBasedEvaluationResult):
    """Result for the ext-triage category.

    Triage is graded as a single pass/fail (`resolved`) that combines three checks against the gold
    decision: exact match on the managed labels, exact match on the open/closed state, and an LLM
    judge verdict on the advisory comment. The per-check booleans are retained for diagnostics.
    """

    json_output: str | None = None
    labels_ok: bool = False
    state_ok: bool = False
    comment_ok: bool = False

    @classmethod
    def create(
        cls,
        context: "EvaluationContext",
        *,
        output: str,
        json_output: str | None,
        labels_ok: bool,
        state_ok: bool,
        comment_ok: bool,
        error_message: str | None = None,
    ) -> Self:
        resolved = labels_ok and state_ok and comment_ok
        return cls(
            **cls._base_fields(context),
            output=output,
            json_output=json_output,
            labels_ok=labels_ok,
            state_ok=state_ok,
            comment_ok=comment_ok,
            resolved=resolved,
            build=resolved,
            error_message=error_message,
        )

    @classmethod
    def create_empty_output(cls, context: "EvaluationContext", error_message: str) -> Self:
        return cls(**cls._base_fields(context), output="", error_message=error_message, resolved=False, build=False)

    @property
    def category_metrics(self) -> dict[str, int | float | bool]:
        return {
            "resolved": self.resolved,
            "labels_ok": self.labels_ok,
            "state_ok": self.state_ok,
            "comment_ok": self.comment_ok,
        }

    @property
    def display_row(self) -> dict[str, str]:
        def mark(ok: bool) -> str:
            return "✓" if ok else "✗"

        return {"Labels": mark(self.labels_ok), "State": mark(self.state_ok), "Comment": mark(self.comment_ok)}
