import dataclasses
from pathlib import Path

import pytest

from bcbench.config import get_config
from bcbench.operations import bc_operations


@pytest.fixture
def cache_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = get_config()
    patched = dataclasses.replace(config, paths=dataclasses.replace(config.paths, bc_artifacts_cache=tmp_path))
    monkeypatch.setattr(bc_operations, "_config", patched)
    return tmp_path


def _make_version(cache_root: Path, version: str) -> Path:
    root = cache_root / "sandbox" / version
    root.mkdir(parents=True)
    return root


def test_resolve_artifact_version_root_picks_newest_revision(cache_root: Path):
    _make_version(cache_root, "27.2.1.0")
    newest = _make_version(cache_root, "27.2.10.5")

    assert bc_operations.resolve_artifact_version_root("27.2") == newest


def test_resolve_artifact_version_root_returns_none_when_absent(cache_root: Path):
    _make_version(cache_root, "26.0.1.0")

    assert bc_operations.resolve_artifact_version_root("27.2") is None


def test_copy_symbol_apps_copies_all_app_files(cache_root: Path, tmp_path: Path):
    version_root = _make_version(cache_root, "27.2.3.4")
    (version_root / "w1" / "Extensions").mkdir(parents=True)
    (version_root / "w1" / "Extensions" / "BaseApp.app").write_text("a")
    (version_root / "platform" / "Applications").mkdir(parents=True)
    (version_root / "platform" / "Applications" / "System.app").write_text("b")

    project_dir = tmp_path / "project"
    bc_operations.copy_symbol_apps(project_dir, "27.2")

    alpackages = project_dir / ".alpackages"
    copied = sorted(p.name for p in alpackages.glob("*.app"))
    assert copied == ["BaseApp.app", "System.app"]


def test_copy_symbol_apps_raises_when_version_missing(cache_root: Path, tmp_path: Path):
    with pytest.raises(FileNotFoundError, match=r"Run scripts/Download-BCSymbols.ps1"):
        bc_operations.copy_symbol_apps(tmp_path / "project", "99.9")


def test_copy_symbol_apps_raises_when_no_app_files(cache_root: Path, tmp_path: Path):
    _make_version(cache_root, "27.2.3.4")

    with pytest.raises(FileNotFoundError, match=r"No \*.app files found"):
        bc_operations.copy_symbol_apps(tmp_path / "project", "27.2")
