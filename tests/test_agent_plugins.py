import json
import os
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
    """Enabled entries are validated before a run starts, so a typo fails fast rather than mid-agent."""

    def test_github_requires_repo_and_revision(self):
        with pytest.raises(ValueError, match=r"requires \['repo', 'revision'\]"):
            PluginConfig(name="x", source="github", path=".")

    def test_local_rejects_github_only_fields(self, tmp_path):
        with pytest.raises(ValueError, match=r"does not take \['repo'\]"):
            PluginConfig(name="x", source="local", path=str(tmp_path), repo="o/r")

    def test_local_requires_absolute_path(self):
        with pytest.raises(ValueError, match="requires an absolute 'path'"):
            PluginConfig(name="x", source="local", path="relative/plugin")

    def test_local_requires_an_absolute_path_on_this_os(self):
        # "C:/..." is absolute on Windows but not on Linux, so an OS-specific path must not be shipped
        with pytest.raises(ValueError, match="requires an absolute 'path'"):
            PluginConfig(name="x", source="local", path="C:/plugins/x" if os.name != "nt" else "/plugins/x")

    def test_unknown_source_rejected(self, tmp_path):
        # Values below are invalid on purpose: config.yaml is untyped, so the validator is the guard
        with pytest.raises(ValueError, match="'local' or 'github'"):
            PluginConfig(name="x", source="marketplace", path=str(tmp_path))  # ty: ignore[invalid-argument-type]

    def test_misspelled_key_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            PluginConfig(name="x", source="local", path=str(tmp_path), commit="abc")  # ty: ignore[unknown-argument]

    def test_enabled_entry_is_validated(self):
        with pytest.raises(ValueError, match="requires an absolute 'path'"):
            resolve_config_plugins({"plugins": [{"name": "x", "source": "local", "enabled": True, "path": "relative"}]})

    def test_disabled_entry_is_inert(self):
        # A disabled entry must never break a run - it may hold a path that is only valid on another OS
        assert resolve_config_plugins({"plugins": [{"name": "x", "source": "local", "enabled": False, "path": "C:/only/valid/on/windows"}]}) == {}

    @pytest.mark.parametrize("revision", ["refs/heads/main", "main", "v1.2.3", "HEAD", "a" * 7, "a" * 41, "z" * 40])
    def test_revision_that_is_not_a_commit_sha_is_rejected(self, revision):
        # A moving ref would let two runs recording the same revision load different plugin code
        with pytest.raises(ValueError, match="String should match pattern"):
            PluginConfig(**_github_entry(revision=revision))

    @pytest.mark.parametrize("repo", ["superpowers", "https://github.com/obra/superpowers", "obra/superpowers/plugins"])
    def test_repo_that_is_not_an_owner_slash_repo_slug_is_rejected(self, repo):
        with pytest.raises(ValueError, match="String should match pattern"):
            PluginConfig(**_github_entry(repo=repo))

    def test_github_record_is_name_at_revision(self):
        assert PluginConfig(**_github_entry()).record == f"superpowers@{'a' * 40}"

    def test_local_record_is_name_at_local(self, tmp_path):
        assert PluginConfig(**_local_entry(tmp_path)).record == "probe@local"


@pytest.mark.usefixtures("plugin_root")
class TestResolveConfigPlugins:
    def test_no_enabled_entries_resolves_to_nothing(self, tmp_path):
        assert resolve_config_plugins({"plugins": [_local_entry(tmp_path, enabled=False)]}) == {}

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


@pytest.mark.usefixtures("plugin_root")
class TestGithubPluginConfinement:
    """A cloned plugin must stay inside the plugin root - a clone replaces its destination."""

    @pytest.mark.parametrize("name", ["../escaped", "../../NAV", "nested/name", "."])
    def test_name_escaping_the_plugin_root_is_rejected_before_cloning(self, name):
        with patch("bcbench.agent.shared.plugin.clone_repo_at_revision") as clone, pytest.raises(AgentError, match="must be a single directory directly under"):
            resolve_config_plugins({"plugins": [_github_entry(name=name)]})

        clone.assert_not_called()

    @pytest.mark.parametrize("path", ["../other-plugin", "plugins/../../elsewhere", "/absolute/plugin"])
    def test_path_escaping_the_clone_is_rejected(self, path):
        with (
            patch("bcbench.agent.shared.plugin.clone_repo_at_revision", side_effect=lambda repo, revision, destination: _make_plugin(destination)),
            pytest.raises(AgentError, match="resolves outside its clone"),
        ):
            resolve_config_plugins({"plugins": [_github_entry(path=path)]})


class TestShippedConfig:
    def test_shipped_config_resolves_on_any_os(self):
        # Entries are disabled, so this must hold even though the `local` example carries a Windows path
        with patch.object(Path, "is_absolute", return_value=False):  # simulate posix path semantics
            assert resolve_config_plugins({"plugins": _shipped_plugins()}) == {}

    def test_shipped_entries_are_disabled_by_default(self):
        assert not [entry for entry in _shipped_plugins() if entry.get("enabled")]

    def test_every_shipped_github_entry_parses(self):
        # `local` entries are excluded: an absolute path is machine-specific by nature
        assert [PluginConfig(**entry).name for entry in _shipped_plugins() if entry["source"] == "github"]

    def test_bundled_example_is_a_loadable_plugin(self):
        example = get_config().paths.agent_share_dir / "plugins" / "bcbench-example"

        assert (example / _MANIFEST).is_file()
