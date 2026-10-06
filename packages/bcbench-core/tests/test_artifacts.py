from pathlib import Path

import pytest

from bcbench_core.artifacts import DEFAULT_ARTIFACTS_CACHE, copy_symbol_apps, resolve_artifact_version_root


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    return tmp_path / "cache"


def _make_version(cache_root: Path, version: str, artifact_type: str = "sandbox") -> Path:
    root = cache_root / artifact_type / version
    root.mkdir(parents=True)
    return root


def test_default_artifacts_cache_is_bccontainerhelper_default():
    assert Path(r"C:\bcartifacts.cache") == DEFAULT_ARTIFACTS_CACHE


def test_resolve_artifact_version_root_uses_requested_artifact_type(cache_root: Path):
    _make_version(cache_root, "27.2.1.0")
    onprem = _make_version(cache_root, "27.2.1.0", "onprem")

    assert resolve_artifact_version_root("27.2", artifacts_cache=cache_root, artifact_type="onprem") == onprem


def test_copy_symbol_apps_into_custom_symbols_folder(cache_root: Path, tmp_path: Path):
    (_make_version(cache_root, "27.2.3.4") / "System.app").write_text("b")

    copy_symbol_apps(tmp_path / "project", "27.2", artifacts_cache=cache_root, symbols_dirname="symbols")

    assert (tmp_path / "project" / "symbols" / "System.app").is_file()


@pytest.mark.parametrize(("older", "newer"), [("27.2.1.0", "27.2.10.5"), ("27.2.9.0", "27.2.10.0"), ("27.2.10.9", "27.2.10.10")])
def test_resolve_artifact_version_root_picks_newest_revision(cache_root: Path, older: str, newer: str):
    _make_version(cache_root, older)
    newest = _make_version(cache_root, newer)

    assert resolve_artifact_version_root("27.2", artifacts_cache=cache_root) == newest


def test_resolve_artifact_version_root_returns_none_when_absent(cache_root: Path):
    _make_version(cache_root, "26.0.1.0")

    assert resolve_artifact_version_root("27.2", artifacts_cache=cache_root) is None


def test_copy_symbol_apps_copies_all_app_files(cache_root: Path, tmp_path: Path):
    version_root = _make_version(cache_root, "27.2.3.4")
    (version_root / "w1" / "Extensions").mkdir(parents=True)
    (version_root / "w1" / "Extensions" / "BaseApp.app").write_text("a")
    (version_root / "platform" / "Applications").mkdir(parents=True)
    (version_root / "platform" / "Applications" / "System.app").write_text("b")

    project_dir = tmp_path / "project"
    copy_symbol_apps(project_dir, "27.2", artifacts_cache=cache_root)

    alpackages = project_dir / ".alpackages"
    copied = sorted(p.name for p in alpackages.glob("*.app"))
    assert copied == ["BaseApp.app", "System.app"]


def test_copy_symbol_apps_raises_when_version_missing(cache_root: Path, tmp_path: Path):
    with pytest.raises(FileNotFoundError, match=r"No BC artifact for version 99.9"):
        copy_symbol_apps(tmp_path / "project", "99.9", artifacts_cache=cache_root)


def test_copy_symbol_apps_raises_when_no_app_files(cache_root: Path, tmp_path: Path):
    _make_version(cache_root, "27.2.3.4")

    with pytest.raises(FileNotFoundError, match=r"No \*.app files found"):
        copy_symbol_apps(tmp_path / "project", "27.2", artifacts_cache=cache_root)
