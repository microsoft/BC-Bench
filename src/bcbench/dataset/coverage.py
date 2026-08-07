"""Per-article coverage tracking for the code-review dataset.

Gold entries are annotated with the BCQuality knowledge article(s) they exercise
(`<domain>/<slug>`). This module aggregates those annotations and, when a BCQuality
checkout is available, compares them against the full article inventory to surface
which articles have zero gold coverage.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from bcbench.dataset.codereview import CodeReviewEntry

# Relative to a BCQuality checkout root; knowledge articles live here as
# `<domain>/<slug>.md`, so the article id is the relative path minus the suffix.
_KNOWLEDGE_SUBDIR = Path("microsoft") / "knowledge"
_BCQUALITY_ROOT_ENV = "BCQUALITY_ROOT"


class ArticleCoverage(BaseModel):
    """One article and the gold entries that exercise it."""

    model_config = ConfigDict(frozen=True)

    article: str
    domain: str
    entry_ids: list[str] = Field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.entry_ids)


class CoverageReport(BaseModel):
    """Per-article coverage of the code-review dataset."""

    model_config = ConfigDict(frozen=True)

    covered: list[ArticleCoverage] = Field(default_factory=list)
    zero_coverage: list[str] = Field(default_factory=list)
    unknown_articles: list[str] = Field(default_factory=list)
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


def _domain_of(article: str) -> str:
    return article.split("/", 1)[0]


def collect_declared_articles(entries: Sequence[CodeReviewEntry]) -> dict[str, list[str]]:
    """Map each declared article to the sorted, de-duplicated entry ids that declare it."""
    article_to_entries: dict[str, set[str]] = {}
    for entry in entries:
        for article in entry.declared_articles():
            article_to_entries.setdefault(article, set()).add(entry.instance_id)
    return {article: sorted(ids) for article, ids in article_to_entries.items()}


def enumerate_inventory(bcquality_root: Path) -> set[str]:
    """Enumerate `<domain>/<slug>` article ids from a BCQuality checkout.

    Only `.md` files under `microsoft/knowledge/` count; sibling `.good.al` / `.bad.al`
    sample files and the generated `knowledge-index.json` are ignored.
    """
    knowledge_dir = bcquality_root / _KNOWLEDGE_SUBDIR
    if not knowledge_dir.is_dir():
        raise FileNotFoundError(f"BCQuality knowledge directory not found: {knowledge_dir}")

    inventory: set[str] = set()
    for path in knowledge_dir.rglob("*.md"):
        relative = path.relative_to(knowledge_dir).with_suffix("")
        inventory.add(relative.as_posix())
    return inventory


def resolve_bcquality_root(explicit: Path | str | None = None) -> Path | None:
    """Resolve a BCQuality checkout root from an explicit value or `BCQUALITY_ROOT`.

    Returns None when neither is set, so callers can degrade to declared-only coverage.
    """
    candidate = explicit if explicit is not None else os.environ.get(_BCQUALITY_ROOT_ENV)
    if not candidate:
        return None
    return Path(candidate).expanduser()


def build_coverage_report(
    entries: Sequence[CodeReviewEntry],
    inventory: Iterable[str] | None = None,
) -> CoverageReport:
    """Compute per-article coverage.

    When `inventory` is provided, articles in the inventory with no declaring entry are
    reported as `zero_coverage`, and declared articles absent from the inventory (typos /
    stale slugs) are reported as `unknown_articles`. Without an inventory, only declared
    articles are reported (`covered`), and zero-coverage cannot be determined.
    """
    declared = collect_declared_articles(entries)
    inventory_set = set(inventory) if inventory is not None else None

    covered: list[ArticleCoverage] = []
    unknown: list[str] = []
    for article in sorted(declared):
        if inventory_set is not None and article not in inventory_set:
            unknown.append(article)
            continue
        covered.append(ArticleCoverage(article=article, domain=_domain_of(article), entry_ids=declared[article]))

    zero_coverage: list[str] = []
    if inventory_set is not None:
        zero_coverage = sorted(inventory_set - set(declared))

    unannotated = sorted(e.instance_id for e in entries if not e.declared_articles())

    return CoverageReport(
        covered=covered,
        zero_coverage=zero_coverage,
        unknown_articles=sorted(unknown),
        unannotated_entry_ids=unannotated,
        total_entries=len(entries),
        inventory_available=inventory_set is not None,
    )
