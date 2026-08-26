"""Analyze BCQuality article coverage in the code-review dataset."""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from bcbench.dataset.codereview import ArticleId, CodeReviewEntry

_KNOWLEDGE_SUBDIR = Path("microsoft") / "knowledge"
_BCQUALITY_ROOT_ENV = "BCQUALITY_ROOT"


class ArticleCoverage(BaseModel):
    """One article and the gold entries that exercise it."""

    model_config = ConfigDict(frozen=True)

    article: ArticleId
    domain: str
    entry_ids: list[str] = Field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.entry_ids)


class CoverageReport(BaseModel):
    """Per-article coverage of the code-review dataset."""

    model_config = ConfigDict(frozen=True)

    covered: list[ArticleCoverage] = Field(default_factory=list)
    zero_coverage: list[ArticleId] = Field(default_factory=list)
    unknown_articles: list[ArticleId] = Field(default_factory=list)
    unannotated_entry_ids: list[str] = Field(default_factory=list)
    total_entries: int = 0
    inventory_available: bool = False

    @property
    def inventory_size(self) -> int:
        if not self.inventory_available:
            return 0
        return len(self.covered) + len(self.zero_coverage)

    @property
    def annotated_entries(self) -> int:
        return self.total_entries - len(self.unannotated_entry_ids)


def _domain_of(article: ArticleId) -> str:
    return article.split("/", 1)[0]


def collect_declared_articles(entries: Sequence[CodeReviewEntry]) -> dict[ArticleId, list[str]]:
    """Map each declared article to the sorted, de-duplicated entry ids that declare it."""
    article_to_entries: dict[ArticleId, set[str]] = {}
    for entry in entries:
        for article in entry.declared_articles():
            article_to_entries.setdefault(article, set()).add(entry.instance_id)
    return {article: sorted(ids) for article, ids in article_to_entries.items()}


def enumerate_inventory(bcquality_root: Path) -> set[ArticleId]:
    """Enumerate article ids from a BCQuality checkout."""
    knowledge_dir = bcquality_root / _KNOWLEDGE_SUBDIR
    if not knowledge_dir.is_dir():
        raise FileNotFoundError(f"BCQuality knowledge directory not found: {knowledge_dir}")

    inventory: set[ArticleId] = set()
    for path in knowledge_dir.rglob("*.md"):
        relative = path.relative_to(knowledge_dir).with_suffix("")
        inventory.add(relative.as_posix())
    return inventory


def resolve_bcquality_root(explicit: Path | str | None = None) -> Path | None:
    """Resolve a BCQuality checkout root from an explicit value or `BCQUALITY_ROOT`."""
    candidate = explicit if explicit is not None else os.environ.get(_BCQUALITY_ROOT_ENV)
    if not candidate:
        return None
    return Path(candidate).expanduser()


def build_coverage_report(
    entries: Sequence[CodeReviewEntry],
    inventory: Iterable[ArticleId] | None = None,
) -> CoverageReport:
    """Compute per-article coverage against an optional BCQuality inventory."""
    declared = collect_declared_articles(entries)
    inventory_set = set(inventory) if inventory is not None else None

    covered: list[ArticleCoverage] = []
    unknown: list[ArticleId] = []
    for article in sorted(declared):
        if inventory_set is not None and article not in inventory_set:
            unknown.append(article)
            continue
        covered.append(ArticleCoverage(article=article, domain=_domain_of(article), entry_ids=declared[article]))

    zero_coverage: list[ArticleId] = []
    if inventory_set is not None:
        zero_coverage = sorted(inventory_set - set(declared))

    unannotated = sorted(entry.instance_id for entry in entries if not entry.declared_articles())

    return CoverageReport(
        covered=covered,
        zero_coverage=zero_coverage,
        unknown_articles=sorted(unknown),
        unannotated_entry_ids=unannotated,
        total_entries=len(entries),
        inventory_available=inventory_set is not None,
    )
