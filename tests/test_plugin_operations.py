import json
from pathlib import Path

import pytest

from bcbench.exceptions import AgentError
from bcbench.operations import plugin_operations as po
from tests.conftest import create_dataset_entry


def _make_marketplace(root: Path, manifest_rel: str = ".claude-plugin/marketplace.json", name: str = "probe-mp") -> Path:
    """Create a minimal marketplace directory and return its root."""
    manifest = root / manifest_rel
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"name": name, "plugins": [{"name": "probe-plugin", "source": "./probe-plugin"}]}), encoding="utf-8")
    plugin_json = root / "probe-plugin" / ".claude-plugin" / "plugin.json"
    plugin_json.parent.mkdir(parents=True, exist_ok=True)
    plugin_json.write_text(json.dumps({"name": "probe-plugin", "version": "0.0.1"}), encoding="utf-8")
    return root


def test_read_marketplace_name_claude_plugin_path(tmp_path):
    _make_marketplace(tmp_path, ".claude-plugin/marketplace.json", name="my-mp")
    assert po._read_marketplace_name(tmp_path) == "my-mp"


def test_read_marketplace_name_github_plugin_path(tmp_path):
    _make_marketplace(tmp_path, ".github/plugin/marketplace.json", name="gh-mp")
    assert po._read_marketplace_name(tmp_path) == "gh-mp"


def test_read_marketplace_name_missing_raises(tmp_path):
    with pytest.raises(AgentError, match="marketplace.json"):
        po._read_marketplace_name(tmp_path)


def test_materialize_marketplace_clones_at_commit(tmp_path, monkeypatch):
    plugins_root = tmp_path / "plugins_root"
    plugins_root.mkdir()

    def fake_clone(repo: str, commit: str, dest: Path) -> None:
        _make_marketplace(dest, name="cloned-mp")

    monkeypatch.setattr(po, "clone_at_commit", fake_clone)
    entry = create_dataset_entry()
    entry_cfg = {"source": "marketplace", "repo": "github/awesome-copilot", "commit": "a" * 40, "plugins": ["probe-plugin"]}

    marketplace_dir, record_suffix = po._materialize(entry_cfg, entry, plugins_root)

    assert (marketplace_dir / ".claude-plugin" / "marketplace.json").is_file()
    assert record_suffix == "a" * 40


def test_materialize_local_copies_from_instructions(tmp_path, monkeypatch):
    plugins_root = tmp_path / "plugins_root"
    plugins_root.mkdir()
    source_root = tmp_path / "instructions"
    _make_marketplace(source_root / "plugins" / "my-mp", name="local-mp")

    monkeypatch.setattr(po, "_get_source_instructions_path", lambda repo: source_root)
    entry = create_dataset_entry()
    entry_cfg = {"source": "local", "path": "plugins/my-mp", "plugins": ["probe-plugin"]}

    marketplace_dir, record_suffix = po._materialize(entry_cfg, entry, plugins_root)

    assert (marketplace_dir / ".claude-plugin" / "marketplace.json").is_file()
    assert record_suffix == "local"


def test_materialize_local_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(po, "_get_source_instructions_path", lambda repo: tmp_path / "nope")
    entry = create_dataset_entry()
    entry_cfg = {"source": "local", "path": "plugins/absent", "plugins": ["x"]}

    with pytest.raises(AgentError, match="Local plugin marketplace not found"):
        po._materialize(entry_cfg, entry, tmp_path / "plugins_root")


def test_materialize_unknown_source_raises(tmp_path):
    entry = create_dataset_entry()
    with pytest.raises(AgentError, match="Unknown plugin source"):
        po._materialize({"source": "bogus", "plugins": []}, entry, tmp_path)
