"""Tests for per-article BCQuality coverage of the code-review dataset."""

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from bcbench.analysis.bcquality_article_coverage import (
    build_coverage_report,
    collect_declared_articles,
    enumerate_inventory,
    resolve_bcquality_root,
)
from bcbench.dataset import CodeReviewEntry, ReviewComment
from bcbench.dataset.codereview import ArticleId, CodeReviewEntryMetadata
from bcbench.types import EvaluationCategory

_BASE_COMMIT = "70fd0246a0a4dbc72cb183ca719106722c03be4d"


def _entry(
    instance_id: str,
    *,
    comments: list[ReviewComment] | None = None,
    articles: list[ArticleId] | None = None,
) -> CodeReviewEntry:
    metadata = CodeReviewEntryMetadata(area="security", articles=articles or [])
    return CodeReviewEntry(
        instance_id=instance_id,
        created_at="2026-01-01",
        environment_setup_version="27.0",
        base_commit=_BASE_COMMIT,
        patch="diff --git a/src/A.al b/src/A.al\n+x",
        expected_comments=comments or [],
        metadata=metadata,
    )


def _comment(body: str, *, article: ArticleId | None = None) -> ReviewComment:
    return ReviewComment(file="src/A.al", line_start=1, body=body, article=article)


def _require_bcquality_root() -> Path:
    root = resolve_bcquality_root()
    if root is not None:
        return root

    message = "BCQUALITY_ROOT must point to a BCQuality checkout to validate article slugs"
    if os.environ.get("GITHUB_ACTIONS") == "true":
        pytest.fail(message)
    pytest.skip(message)


class TestDeclaredArticles:
    def test_declared_from_comment_and_metadata(self):
        entry = _entry(
            "synthetic__security-001",
            comments=[_comment("finding", article="security/secrettext-for-credentials")],
            articles=["security/permission-set-avoid-wildcard-grants"],
        )
        assert entry.declared_articles() == {
            "security/secrettext-for-credentials",
            "security/permission-set-avoid-wildcard-grants",
        }

    def test_unannotated_entry_declares_nothing(self):
        entry = _entry("synthetic__security-002", comments=[_comment("finding")])
        assert entry.declared_articles() == set()

    def test_article_declared_both_places_is_rejected(self):
        shared = "security/secrettext-for-credentials"
        with pytest.raises(ValidationError, match="declared both per-comment"):
            _entry(
                "synthetic__security-003",
                comments=[_comment("finding", article=shared)],
                articles=[shared],
            )

    def test_collect_maps_article_to_sorted_entry_ids(self):
        shared = "security/validate-user-configurable-urls"
        entries = [
            _entry("synthetic__security-015", comments=[_comment("ssrf", article=shared)]),
            _entry("synthetic__security-011", comments=[_comment("ssrf", article=shared)]),
        ]
        declared = collect_declared_articles(entries)
        assert declared[shared] == ["synthetic__security-011", "synthetic__security-015"]


class TestCoverageReport:
    def test_without_inventory_reports_declared_only(self):
        entries = [
            _entry("synthetic__security-001", comments=[_comment("x", article="security/secrettext-for-credentials")]),
            _entry("synthetic__security-002", comments=[_comment("y")]),
        ]
        report = build_coverage_report(entries, inventory=None)
        assert report.inventory_available is False
        assert report.zero_coverage == []
        assert [c.article for c in report.covered] == ["security/secrettext-for-credentials"]
        assert report.unannotated_entry_ids == ["synthetic__security-002"]
        assert report.annotated_entries == 1

    def test_with_inventory_flags_zero_and_unknown(self):
        inventory = {
            "security/secrettext-for-credentials",
            "security/permission-set-avoid-wildcard-grants",
        }
        entries = [
            _entry("synthetic__security-001", comments=[_comment("x", article="security/secrettext-for-credentials")]),
            _entry("synthetic__security-009", comments=[_comment("z", article="security/made-up-slug")]),
        ]
        report = build_coverage_report(entries, inventory=inventory)
        assert report.inventory_available is True
        assert [c.article for c in report.covered] == ["security/secrettext-for-credentials"]
        assert report.zero_coverage == ["security/permission-set-avoid-wildcard-grants"]
        assert report.unknown_articles == ["security/made-up-slug"]
        assert report.inventory_size == 2

    def test_covered_entry_ids_deduplicated_across_entries(self):
        article = "security/inherent-permissions-minimal-grant"
        entries = [
            _entry("synthetic__security-013", comments=[_comment("a", article=article), _comment("b", article=article)]),
        ]
        report = build_coverage_report(entries, inventory={article})
        assert len(report.covered) == 1
        assert report.covered[0].entry_ids == ["synthetic__security-013"]
        assert report.covered[0].count == 1


class TestInventoryEnumeration:
    def test_enumerate_ignores_al_samples_and_index(self, tmp_path: Path):
        knowledge = tmp_path / "microsoft" / "knowledge" / "security"
        knowledge.mkdir(parents=True)
        (knowledge / "secrettext-for-credentials.md").write_text("x", encoding="utf-8")
        (knowledge / "secrettext-for-credentials.good.al").write_text("x", encoding="utf-8")
        (tmp_path / "microsoft" / "knowledge" / "knowledge-index.json").write_text("{}", encoding="utf-8")
        assert enumerate_inventory(tmp_path) == {"security/secrettext-for-credentials"}

    def test_resolve_prefers_explicit_over_env(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("BCQUALITY_ROOT", str(tmp_path / "from-env"))
        assert resolve_bcquality_root(str(tmp_path / "explicit")) == tmp_path / "explicit"

    def test_resolve_returns_none_without_source(self, monkeypatch):
        monkeypatch.delenv("BCQUALITY_ROOT", raising=False)
        assert resolve_bcquality_root(None) is None

    def test_missing_root_skips_locally(self, monkeypatch):
        monkeypatch.delenv("BCQUALITY_ROOT", raising=False)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        with pytest.raises(pytest.skip.Exception, match="BCQUALITY_ROOT must point"):
            _require_bcquality_root()

    def test_missing_root_fails_in_github_actions(self, monkeypatch):
        monkeypatch.delenv("BCQUALITY_ROOT", raising=False)
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        with pytest.raises(pytest.fail.Exception, match="BCQUALITY_ROOT must point"):
            _require_bcquality_root()


class TestDatasetArticleSlugs:
    @pytest.mark.e2e
    def test_declared_slugs_exist_in_bcquality(self):
        bcquality_root = _require_bcquality_root()
        entries = CodeReviewEntry.load(EvaluationCategory.CODE_REVIEW.dataset_path)
        declared = collect_declared_articles(entries)
        report = build_coverage_report(entries, inventory=enumerate_inventory(bcquality_root))
        unknown = {article: declared[article] for article in report.unknown_articles}
        assert not unknown, f"article slugs not found in {bcquality_root}: {unknown}"
