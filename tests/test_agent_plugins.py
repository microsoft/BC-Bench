import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from bcbench.agent.shared.plugin import resolve_config_plugins
from bcbench.config import get_config
from bcbench.exceptions import AgentError
from bcbench.types import PluginConfig

_MANIFEST = get_config().file_patterns.plugin_manifest


def _make_plugin(root: Path, name: str = "probe-plugin") -> Path:
    """Create a minimal loadable plugin directory and return it."""
    manifest = root / _MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"name": name, "version": "0.0.1"}), encoding="utf-8")
    return root


def _local_entry(path: Path, **overrides) -> dict:
    return {"name": "probe", "source": "local", "enabled": True, "path": str(path), **overrides}


def _github_entry(**overrides) -> dict:
    return {"name": "superpowers", "source": "github", "enabled": True, "repo": "obra/superpowers", "revision": "a" * 40, "path": ".", **overrides}


def _shipped_plugins() -> list[dict]:
    config = yaml.safe_load((get_config().paths.agent_share_dir / "config.yaml").read_text(encoding="utf-8"))
    return config["plugins"]


class TestPluginConfigValidation:
    """Every entry is validated, enabled or not, so a typo surfaces before a run starts."""

    def test_github_requires_repo_and_revision(self):
        with pytest.raises(ValueError, match=r"requires \['repo', 'revision'\]"):
            PluginConfig(name="x", source="github", path=".")

    def test_local_rejects_github_only_fields(self):
        with pytest.raises(ValueError, match=r"does not take \['revision'\]"):
            PluginConfig(name="x", source="local", path="C:/plugins/x", revision="abc")

    def test_local_requires_absolute_path(self):
        with pytest.raises(ValueError, match="requires an absolute 'path'"):
            PluginConfig(name="x", source="local", path="relative/plugin")

    def test_unknown_source_rejected(self):
        # Values below are invalid on purpose: config.yaml is untyped, so the validator is the guard
        with pytest.raises(ValueError, match="'local' or 'github'"):
            PluginConfig(name="x", source="marketplace", path="C:/plugins/x")  # ty: ignore[invalid-argument-type]

    def test_misspelled_key_rejected(self):
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            PluginConfig(name="x", source="local", path="C:/plugins/x", commit="abc")  # ty: ignore[unknown-argument]

    def test_disabled_entry_is_still_validated(self):
        with pytest.raises(ValueError, match="requires an absolute 'path'"):
            resolve_config_plugins({"plugins": [{"name": "x", "source": "local", "enabled": False, "path": "relative"}]})

    @pytest.mark.parametrize(("revision", "expected"), [("a" * 40, f"superpowers@{'a' * 40}"), ("refs/heads/main", "superpowers@refs/heads/main")])
    def test_github_record_is_name_at_revision(self, revision, expected):
        assert PluginConfig(**_github_entry(revision=revision)).record == expected

    def test_local_record_is_name_at_local(self):
        assert PluginConfig(**_local_entry(Path("C:/plugins/x"))).record == "probe@local"


@pytest.mark.usefixtures("plugin_root")
class TestResolveConfigPlugins:
    def test_no_enabled_entries_resolves_to_nothing(self):
        assert resolve_config_plugins({"plugins": [_local_entry(Path("C:/plugins/x"), enabled=False)]}) == {}

    def test_local_plugin_resolves_to_its_absolute_path(self, tmp_path):
        plugin = _make_plugin(tmp_path / "my-plugin")

        assert resolve_config_plugins({"plugins": [_local_entry(plugin)]}) == {"probe@local": plugin}

    def test_local_plugin_expands_user_home(self, tmp_path):
        plugin = _make_plugin(tmp_path / "my-plugin")
        with patch.object(Path, "expanduser", return_value=plugin):
            assert resolve_config_plugins({"plugins": [_local_entry(Path("~/my-plugin"))]}) == {"probe@local": plugin}

    def test_missing_manifest_raises_pointing_at_the_expected_location(self, tmp_path):
        (tmp_path / "not-a-plugin").mkdir()

        with pytest.raises(AgentError, match="has no manifest at"):
            resolve_config_plugins({"plugins": [_local_entry(tmp_path / "not-a-plugin")]})

    def test_github_plugin_is_cloned_into_the_plugin_root(self, plugin_root):
        with patch("bcbench.agent.shared.plugin.clone_repo_at_revision", side_effect=lambda repo, revision, destination: _make_plugin(destination)) as clone:
            resolved = resolve_config_plugins({"plugins": [_github_entry()]})

        clone.assert_called_once_with("obra/superpowers", "a" * 40, plugin_root / "superpowers")
        assert resolved == {f"superpowers@{'a' * 40}": plugin_root / "superpowers"}

    def test_github_plugin_never_lands_in_the_repo_under_evaluation(self, tmp_path, plugin_root):
        with patch("bcbench.agent.shared.plugin.clone_repo_at_revision", side_effect=lambda repo, revision, destination: _make_plugin(destination)):
            resolved = resolve_config_plugins({"plugins": [_github_entry()]})

        testbed = tmp_path / "repo"
        assert not any(directory.is_relative_to(testbed) for directory in resolved.values())
        assert list(resolved.values()) == [plugin_root / "superpowers"]

    def test_github_path_selects_a_subfolder_of_the_clone(self, plugin_root):
        with patch("bcbench.agent.shared.plugin.clone_repo_at_revision", side_effect=lambda repo, revision, destination: _make_plugin(destination / "plugins" / "inner")):
            resolved = resolve_config_plugins({"plugins": [_github_entry(path="plugins/inner")]})

        assert resolved == {f"superpowers@{'a' * 40}": plugin_root / "superpowers" / "plugins" / "inner"}

    def test_preserves_config_order_across_sources(self, tmp_path):
        local = _make_plugin(tmp_path / "local-plugin")

        with patch("bcbench.agent.shared.plugin.clone_repo_at_revision", side_effect=lambda repo, revision, destination: _make_plugin(destination)):
            resolved = resolve_config_plugins({"plugins": [_github_entry(), _local_entry(local)]})

        assert list(resolved) == [f"superpowers@{'a' * 40}", "probe@local"]


class TestShippedConfig:
    def test_every_shipped_entry_parses(self):
        assert [PluginConfig(**entry).name for entry in _shipped_plugins()]

    def test_shipped_entries_are_disabled_by_default(self):
        assert not [entry for entry in _shipped_plugins() if entry.get("enabled")]

    def test_bundled_example_is_a_loadable_plugin(self):
        example = get_config().paths.agent_share_dir / "plugins" / "bcbench-example"

        assert (example / _MANIFEST).is_file()
