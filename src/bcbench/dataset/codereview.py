from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from bcbench.dataset.dataset_entry import BaseDatasetEntry


class ReviewComment(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    line_start: int
    line_end: int | None = None
    body: str
    severity: str = "suggestion"

    def __str__(self) -> str:
        loc = f"{self.file}:{self.line_start}"
        if self.line_end and self.line_end != self.line_start:
            loc += f"-{self.line_end}"
        return f"[{self.severity}] {loc}: {self.body}"


class CodeReviewEntry(BaseDatasetEntry):
    """Dataset entry for the code-review category."""

    expected_comments: list[ReviewComment] = Field(default_factory=list)
    match_line_tolerance: int = Field(default=5, ge=0)

    def get_task(self) -> str:
        return self.patch

    def get_expected_output(self) -> str:
        return "\n".join(str(c) for c in self.expected_comments)
