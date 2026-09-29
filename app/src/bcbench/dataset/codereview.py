from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bcbench.dataset.dataset_entry import EntryMetadata, RepoGroundedEntry

# BCQuality knowledge article id, formatted as `<domain>/<slug>` (e.g. `security/hardcoded-secret`).
ArticleId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*$")]


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
        if normalized in {s.value for s in cls}:
            return cls(normalized)
        if normalized in _SEVERITY_ALIASES:
            return _SEVERITY_ALIASES[normalized]
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
    # BCQuality skills/do.md emits blocker|major|minor|info; map them so engine
    # findings score correctly instead of coercing to unspecified severity.
    "blocker": Severity.CRITICAL,
    "major": Severity.HIGH,
    "minor": Severity.LOW,
}


class ReviewComment(BaseModel):
    # Reject unknown keys so a superseded annotation (e.g. the singular `article` this
    # model used before) fails loudly instead of being dropped into invisible coverage loss.
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 ./_-]*\.(al|json)$")]
    line_start: Annotated[int, Field(ge=1)]
    line_end: Annotated[int, Field(ge=1)] | None = None
    domain: str | None = None
    body: Annotated[str, Field(min_length=1)]
    severity: Severity | None = None
    # BCQuality knowledge articles this finding derives from, as `<domain>/<slug>`
    # (e.g. `security/hardcoded-secret`). A single finding can exercise several articles,
    # most commonly when it pairs a positive requirement with an explicit false-positive
    # boundary. Optional; drives per-article coverage tracking. Entries that leave it
    # empty are counted as unannotated.
    articles: list[ArticleId] = Field(default_factory=list)

    @field_validator("severity", mode="before")
    @classmethod
    def _coerce_severity(cls, value: object) -> Severity | None:
        if value is None or isinstance(value, Severity):
            return value
        return Severity.from_input(str(value))

    @property
    def severity_label(self) -> str:
        return self.severity.value if self.severity is not None else "unspecified"

    def __str__(self) -> str:
        loc = f"{self.file}:{self.line_start}"
        if self.line_end and self.line_end != self.line_start:
            loc += f"-{self.line_end}"
        return f"[{self.severity_label}] {loc}: {self.body}"


class CodeReviewEntryMetadata(EntryMetadata):
    """Code-review-specific entry metadata."""

    # BCQuality knowledge articles this entry exercises as `<domain>/<slug>`. Primarily
    # for false-positive-guard entries (expected_comments=[]) that test an article by
    # omission and thus have no per-comment `articles` to carry the association.
    articles: list[ArticleId] = Field(default_factory=list)


class CodeReviewEntry(RepoGroundedEntry):
    """Dataset entry for the code-review category."""

    metadata: CodeReviewEntryMetadata = Field(default_factory=CodeReviewEntryMetadata)

    expected_comments: list[ReviewComment] = Field(default_factory=list)
    # Comments that are acceptable but not required. If the agent raises a matching
    # comment it is neither rewarded (recall) nor penalized (precision) -- it is dropped
    # from scoring. Use for legitimate-but-debatable or out-of-scope findings that should
    # not force recall yet must not count as false positives. Expected comments take
    # precedence, so a generated comment is only ever neutralized after expected matching.
    ignored_comments: list[ReviewComment] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_article_annotations(self) -> Self:
        """Keep per-comment and entry-level article annotations complementary.

        `metadata.articles` carries the article association for findings no expected
        comment covers (e.g. false-positive-guard entries whose `expected_comments` is
        empty). An article already declared on a comment must not be repeated at entry
        level, so the two annotation sources cannot silently drift apart.
        """
        comment_articles = {article for c in self.expected_comments for article in c.articles}
        overlap = comment_articles & set(self.metadata.articles)
        if overlap:
            raise ValueError(
                f"{self.instance_id}: article(s) {sorted(overlap)} declared both per-comment "
                "and in metadata.articles; entry-level metadata.articles is only for articles "
                "no expected comment already carries"
            )
        return self

    def get_task(self) -> str:
        return self.patch

    def get_expected_output(self) -> str:
        return "\n".join(str(c) for c in self.expected_comments)

    def declared_articles(self) -> set[ArticleId]:
        """BCQuality articles this entry is annotated against.

        Union of every expected comment's `articles` and the entry-level
        `metadata.articles` (which carries the association for false-positive-guard
        entries whose `expected_comments` is empty).
        """
        articles = {article for c in self.expected_comments for article in c.articles}
        articles.update(self.metadata.articles)
        return articles
