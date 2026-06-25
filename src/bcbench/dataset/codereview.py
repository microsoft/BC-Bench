from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bcbench.dataset.dataset_entry import BaseDatasetEntry


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def level(self) -> int:
        return _SEVERITY_LEVELS[self]

    @classmethod
    def from_input(cls, value: str) -> Severity:
        normalized = value.strip().lower()
        try:
            return cls(normalized)
        except ValueError:
            pass
        alias = _SEVERITY_ALIASES.get(normalized)
        if alias is not None:
            return alias
        valid = [s.value for s in cls] + list(_SEVERITY_ALIASES)
        raise ValueError(f"Unknown severity {value!r}; expected one of {valid}")


_SEVERITY_LEVELS: dict[Severity, int] = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
}

_SEVERITY_ALIASES: dict[str, Severity] = {
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "suggestion": Severity.LOW,
    "info": Severity.LOW,
}


class ReviewComment(BaseModel):
    model_config = ConfigDict(frozen=True)

    file: str
    line_start: int
    line_end: int | None = None
    domain: str | None = None
    body: str
    severity: Severity

    @field_validator("severity", mode="before")
    @classmethod
    def _coerce_severity(cls, value: object) -> Severity:
        if isinstance(value, Severity):
            return value
        return Severity.from_input(str(value))

    def __str__(self) -> str:
        loc = f"{self.file}:{self.line_start}"
        if self.line_end and self.line_end != self.line_start:
            loc += f"-{self.line_end}"
        return f"[{self.severity}] {loc}: {self.body}"


class CodeReviewEntry(BaseDatasetEntry):
    """Dataset entry for the code-review category."""

    expected_comments: list[ReviewComment] = Field(default_factory=list)

    def get_task(self) -> str:
        return self.patch

    def get_expected_output(self) -> str:
        return "\n".join(str(c) for c in self.expected_comments)
