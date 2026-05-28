import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.shared.lsp import build_al_lsp_plugin
from bcbench.exceptions import AgentError
from bcbench.types import AgentType, EvaluationCategory
from tests.conftest import create_dataset_entry

_PLUGIN_REL = Path(".bcbench") / "al-lsp-plugin"


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


def _read_lsp(repo_path: Path) -> dict:
    return json.loads((repo_path / _PLUGIN_REL / ".lsp.json").read_text(encoding="utf-8"))


def _read_manifest(repo_path: Path) -> dict:
    return json.loads((repo_path / _PLUGIN_REL / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))


def _build(entry, repo_path, agent_type: AgentType, **kwargs):
    return build_al_lsp_plugin(entry, EvaluationCategory.BUG_FIX, repo_path, agent_type, **kwargs)


@pytest.fixture(params=[AgentType.COPILOT, AgentType.CLAUDE], ids=lambda a: a.value)
def agent_type(request) -> AgentType:
    """Parametrize across both agents — every shared behavior gets tested twice."""
    return request.param


class TestSharedBehavior:
    """Behavior that must hold for both Copilot and Claude variants."""

    def test_returns_none_when_disabled(self, entry, repo_path, agent_type):
        assert _build(entry, repo_path, agent_type, al_lsp=False) is None
        assert not (repo_path / _PLUGIN_REL).exists()

    def test_removes_stale_plugin_when_disabled(self, entry, repo_path, agent_type):
        plugin_dir = repo_path / _PLUGIN_REL
        (plugin_dir / ".claude-plugin").mkdir(parents=True)
        (plugin_dir / ".claude-plugin" / "plugin.json").write_text("{}")
        (plugin_dir / ".lsp.json").write_text("{}")

        _build(entry, repo_path, agent_type, al_lsp=False)

        assert not plugin_dir.exists()

    @pytest.mark.usefixtures("artifact_paths")
    def test_returns_plugin_dir_when_enabled(self, entry, repo_path, agent_type):
        assert _build(entry, repo_path, agent_type, al_lsp=True) == repo_path / _PLUGIN_REL

    @pytest.mark.usefixtures("artifact_paths")
    def test_writes_minimal_manifest(self, entry, repo_path, agent_type):
        _build(entry, repo_path, agent_type, al_lsp=True)
        assert _read_manifest(repo_path)["name"] == "al-lsp"  # only required field

    @pytest.mark.usefixtures("artifact_paths")
    def test_command_is_unqualified_al(self, entry, repo_path, agent_type):
        # Copilot CLI silently rejects absolute command paths in LSP `command`; must resolve via PATH.
        _build(entry, repo_path, agent_type, al_lsp=True)
        config = _read_lsp(repo_path)
        # Navigate to the server entry regardless of schema wrapper:
        server = config["lspServers"]["altool"] if "lspServers" in config else config["altool"]
        assert server["command"] == "al"

    @pytest.mark.usefixtures("artifact_paths")
    def test_project_paths_inserted_after_launchlspserver(self, entry, repo_path, agent_type):
        _build(entry, repo_path, agent_type, al_lsp=True)
        config = _read_lsp(repo_path)
        server = config["lspServers"]["altool"] if "lspServers" in config else config["altool"]
        args = server["args"]
        launch_idx = args.index("launchlspserver")
        assert args[launch_idx + 1] == str(repo_path / "src/App")
        assert args[launch_idx + 2] == str(repo_path / "src/TestApp")

    @pytest.mark.usefixtures("artifact_paths")
    def test_artifact_cache_paths_used_for_package_cache(self, entry, repo_path, agent_type):
        _build(entry, repo_path, agent_type, al_lsp=True)
        config = _read_lsp(repo_path)
        server = config["lspServers"]["altool"] if "lspServers" in config else config["altool"]
        args = server["args"]
        cache_idx = args.index("--packagecachepath")
        probing_idx = args.index("--assemblyprobingpaths")
        assert args[cache_idx + 1 : probing_idx] == ["C:/cache/w1/Extensions", "C:/cache/platform/Applications"]

    @pytest.mark.usefixtures("no_artifacts")
    def test_uses_container_compiler_folder_when_present(self, entry, repo_path, agent_type, tmp_path):
        compiler_root = tmp_path / "compiler" / "test-container"
        (compiler_root / "symbols").mkdir(parents=True)
        with patch(
            "bcbench.agent.shared.lsp.compiler_symbol_folder_for_container",
            return_value=(compiler_root, compiler_root / "symbols"),
        ):
            _build(entry, repo_path, agent_type, al_lsp=True, container_name="test-container")

        config = _read_lsp(repo_path)
        server = config["lspServers"]["altool"] if "lspServers" in config else config["altool"]
        cache_idx = server["args"].index("--packagecachepath")
        assert server["args"][cache_idx + 1] == str(compiler_root / "symbols")

    @pytest.mark.usefixtures("artifact_paths")
    def test_container_compiler_folder_wins_over_artifact_cache(self, entry, repo_path, agent_type, tmp_path):
        # When BOTH sources exist, the container compiler folder must win — same arg
        # shape as AL-MCP, easier to debug a "which symbols set is this?" question.
        compiler_root = tmp_path / "compiler" / "test-container"
        (compiler_root / "symbols").mkdir(parents=True)
        with patch(
            "bcbench.agent.shared.lsp.compiler_symbol_folder_for_container",
            return_value=(compiler_root, compiler_root / "symbols"),
        ):
            _build(entry, repo_path, agent_type, al_lsp=True, container_name="test-container")

        config = _read_lsp(repo_path)
        server = config["lspServers"]["altool"] if "lspServers" in config else config["altool"]
        args = server["args"]
        cache_idx = args.index("--packagecachepath")
        end_idx = args.index("--assemblyprobingpaths") if "--assemblyprobingpaths" in args else len(args)
        assert args[cache_idx + 1 : end_idx] == [str(compiler_root / "symbols")]

    @pytest.mark.usefixtures("no_artifacts")
    def test_raises_with_download_hint_when_neither_source_available(self, entry, repo_path, agent_type):
        with pytest.raises(AgentError, match=r"Download-BCSymbols\.ps1"):
            _build(entry, repo_path, agent_type, al_lsp=True, container_name="")


class TestAgentSpecificSchema:
    """Each agent's `.lsp.json` schema differs slightly — verify the right keys land for each."""

    @pytest.mark.usefixtures("artifact_paths")
    def test_copilot_uses_lspservers_wrapper_with_file_extensions(self, entry, repo_path):
        _build(entry, repo_path, AgentType.COPILOT, al_lsp=True)
        config = _read_lsp(repo_path)
        # Copilot: `lspServers` wrapper + `fileExtensions`.
        assert "lspServers" in config
        assert config["lspServers"]["altool"]["fileExtensions"] == {".al": "al"}
        assert "extensionToLanguage" not in config["lspServers"]["altool"]

    @pytest.mark.usefixtures("artifact_paths")
    def test_claude_uses_flat_schema_with_extension_to_language(self, entry, repo_path):
        _build(entry, repo_path, AgentType.CLAUDE, al_lsp=True)
        config = _read_lsp(repo_path)
        # Claude: top-level server name (no wrapper) + `extensionToLanguage`.
        assert "lspServers" not in config
        assert config["altool"]["extensionToLanguage"] == {".al": "al"}
        assert "fileExtensions" not in config["altool"]
