import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.shared.lsp import build_al_lsp_plugin
from bcbench.exceptions import AgentError
from bcbench.types import AgentHarness, ContainerConfig, EvaluationCategory
from tests.conftest import create_dataset_entry

_PLUGIN_FOLDER = "al-lsp-plugin"


@pytest.fixture(autouse=True)
def _isolated_plugin_root(plugin_root):
    """Every test in this module writes its plugin into a temp root, never the repo's own `.bcbench/`."""
    return plugin_root


@pytest.fixture
def entry():
    return create_dataset_entry(project_paths=["src/App", "src/TestApp"])


@pytest.fixture
def repo_path(tmp_path) -> Path:
    return tmp_path / "repo"


@pytest.fixture
def artifact_paths():
    with patch(
        "bcbench.agent.shared.lsp.resolve_artifact_lsp_paths",
        return_value=(["C:/cache/w1/Extensions", "C:/cache/platform/Applications"], ["C:/cache/platform"]),
    ) as m:
        yield m


@pytest.fixture
def no_artifacts():
    with patch("bcbench.agent.shared.lsp.resolve_artifact_lsp_paths", return_value=None) as m:
        yield m


def _read_lsp(plugin_root: Path) -> dict:
    return json.loads((plugin_root / _PLUGIN_FOLDER / ".lsp.json").read_text(encoding="utf-8"))


def _read_manifest(plugin_root: Path) -> dict:
    return json.loads((plugin_root / _PLUGIN_FOLDER / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))


def _build(entry, repo_path, harness: AgentHarness, **kwargs):
    return build_al_lsp_plugin(entry, EvaluationCategory.BUG_FIX, repo_path, harness, **kwargs)


@pytest.fixture(params=[AgentHarness.COPILOT, AgentHarness.CLAUDE], ids=lambda a: a.value)
def harness(request) -> AgentHarness:
    """Parametrize across both agents — every shared behavior gets tested twice."""
    return request.param


class TestSharedBehavior:
    """Behavior that must hold for both Copilot and Claude variants."""

    def test_returns_none_when_disabled(self, entry, repo_path, harness, plugin_root):
        assert _build(entry, repo_path, harness, al_lsp=False) is None
        assert not (plugin_root / _PLUGIN_FOLDER).exists()

    def test_removes_stale_plugin_when_disabled(self, entry, repo_path, harness, plugin_root):
        plugin_dir = plugin_root / _PLUGIN_FOLDER
        (plugin_dir / ".claude-plugin").mkdir(parents=True)
        (plugin_dir / ".claude-plugin" / "plugin.json").write_text("{}")
        (plugin_dir / ".lsp.json").write_text("{}")

        _build(entry, repo_path, harness, al_lsp=False)

        assert not plugin_dir.exists()

    @pytest.mark.usefixtures("artifact_paths")
    def test_returns_plugin_dir_when_enabled(self, entry, repo_path, harness, plugin_root):
        assert _build(entry, repo_path, harness, al_lsp=True) == plugin_root / _PLUGIN_FOLDER

    @pytest.mark.usefixtures("artifact_paths")
    def test_plugin_dir_is_outside_the_repo_under_evaluation(self, entry, repo_path, harness):
        # Plugin content must never reach the evaluated repo's diff or the agent's working directory
        plugin_dir = _build(entry, repo_path, harness, al_lsp=True)
        assert plugin_dir is not None
        assert not plugin_dir.is_relative_to(repo_path)

    @pytest.mark.usefixtures("artifact_paths")
    def test_writes_minimal_manifest(self, entry, repo_path, harness, plugin_root):
        _build(entry, repo_path, harness, al_lsp=True)
        assert _read_manifest(plugin_root)["name"] == "al-lsp"  # only required field

    @pytest.mark.usefixtures("artifact_paths")
    def test_command_is_unqualified_al(self, entry, repo_path, harness, plugin_root):
        # Copilot CLI silently rejects absolute command paths in LSP `command`; must resolve via PATH.
        _build(entry, repo_path, harness, al_lsp=True)
        config = _read_lsp(plugin_root)
        # Navigate to the server entry regardless of schema wrapper:
        server = config["lspServers"]["altool"] if "lspServers" in config else config["altool"]
        assert server["command"] == "al"

    @pytest.mark.usefixtures("artifact_paths")
    def test_project_paths_inserted_after_launchlspserver(self, entry, repo_path, harness, plugin_root):
        _build(entry, repo_path, harness, al_lsp=True)
        config = _read_lsp(plugin_root)
        server = config["lspServers"]["altool"] if "lspServers" in config else config["altool"]
        args = server["args"]
        launch_idx = args.index("launchlspserver")
        assert args[launch_idx + 1] == str(repo_path / "src/App")
        assert args[launch_idx + 2] == str(repo_path / "src/TestApp")

    @pytest.mark.usefixtures("artifact_paths")
    def test_artifact_cache_paths_used_for_package_cache(self, entry, repo_path, harness, plugin_root):
        _build(entry, repo_path, harness, al_lsp=True)
        config = _read_lsp(plugin_root)
        server = config["lspServers"]["altool"] if "lspServers" in config else config["altool"]
        args = server["args"]
        cache_idx = args.index("--packagecachepath")
        probing_idx = args.index("--assemblyprobingpaths")
        assert args[cache_idx + 1 : probing_idx] == ["C:/cache/w1/Extensions", "C:/cache/platform/Applications"]

    @pytest.mark.usefixtures("no_artifacts")
    def test_uses_container_compiler_folder_when_present(self, entry, repo_path, harness, tmp_path, plugin_root):
        compiler_root = tmp_path / "compiler" / "test-container"
        (compiler_root / "symbols").mkdir(parents=True)
        with patch(
            "bcbench.agent.shared.lsp.compiler_symbol_folder_for_container",
            return_value=(compiler_root, compiler_root / "symbols"),
        ):
            _build(entry, repo_path, harness, al_lsp=True, container=ContainerConfig("test-container", "", "", "CRONUS"))

        config = _read_lsp(plugin_root)
        server = config["lspServers"]["altool"] if "lspServers" in config else config["altool"]
        cache_idx = server["args"].index("--packagecachepath")
        assert server["args"][cache_idx + 1] == str(compiler_root / "symbols")

    @pytest.mark.usefixtures("artifact_paths")
    def test_container_compiler_folder_wins_over_artifact_cache(self, entry, repo_path, harness, tmp_path, plugin_root):
        # When BOTH sources exist, the container compiler folder must win — same arg
        # shape as AL-MCP, easier to debug a "which symbols set is this?" question.
        compiler_root = tmp_path / "compiler" / "test-container"
        (compiler_root / "symbols").mkdir(parents=True)
        with patch(
            "bcbench.agent.shared.lsp.compiler_symbol_folder_for_container",
            return_value=(compiler_root, compiler_root / "symbols"),
        ):
            _build(entry, repo_path, harness, al_lsp=True, container=ContainerConfig("test-container", "", "", "CRONUS"))

        config = _read_lsp(plugin_root)
        server = config["lspServers"]["altool"] if "lspServers" in config else config["altool"]
        args = server["args"]
        cache_idx = args.index("--packagecachepath")
        end_idx = args.index("--assemblyprobingpaths") if "--assemblyprobingpaths" in args else len(args)
        assert args[cache_idx + 1 : end_idx] == [str(compiler_root / "symbols")]

    @pytest.mark.usefixtures("no_artifacts")
    def test_raises_with_download_hint_when_neither_source_available(self, entry, repo_path, harness):
        with pytest.raises(AgentError, match=r"Download-BCSymbols\.ps1"):
            _build(entry, repo_path, harness, al_lsp=True, container=None)


class TestAgentSpecificSchema:
    """Each agent's `.lsp.json` schema differs slightly — verify the right keys land for each."""

    @pytest.mark.usefixtures("artifact_paths")
    def test_copilot_uses_lspservers_wrapper_with_file_extensions(self, entry, repo_path, plugin_root):
        _build(entry, repo_path, AgentHarness.COPILOT, al_lsp=True)
        config = _read_lsp(plugin_root)
        # Copilot: `lspServers` wrapper + `fileExtensions`.
        assert "lspServers" in config
        assert config["lspServers"]["altool"]["fileExtensions"] == {".al": "al"}
        assert "extensionToLanguage" not in config["lspServers"]["altool"]

    @pytest.mark.usefixtures("artifact_paths")
    def test_claude_uses_flat_schema_with_extension_to_language(self, entry, repo_path, plugin_root):
        _build(entry, repo_path, AgentHarness.CLAUDE, al_lsp=True)
        config = _read_lsp(plugin_root)
        # Claude: top-level server name (no wrapper) + `extensionToLanguage`.
        assert "lspServers" not in config
        assert config["altool"]["extensionToLanguage"] == {".al": "al"}
        assert "fileExtensions" not in config["altool"]
