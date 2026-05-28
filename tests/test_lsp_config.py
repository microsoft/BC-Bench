import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.shared.lsp import build_claude_lsp_plugin, build_copilot_lsp_config
from bcbench.exceptions import AgentError
from bcbench.types import EvaluationCategory
from tests.conftest import create_dataset_entry


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


class TestCopilotLspConfig:
    @staticmethod
    def _read(repo_path: Path) -> dict:
        return json.loads((repo_path / ".github" / "lsp.json").read_text(encoding="utf-8"))

    @staticmethod
    def _build(entry, repo_path, **kwargs):
        return build_copilot_lsp_config(entry, EvaluationCategory.BUG_FIX, repo_path, **kwargs)

    def test_returns_false_when_disabled(self, entry, repo_path):
        assert self._build(entry, repo_path, al_lsp=False) is False
        assert not (repo_path / ".github" / "lsp.json").exists()

    def test_removes_stale_config_when_disabled(self, entry, repo_path):
        lsp_path = repo_path / ".github" / "lsp.json"
        lsp_path.parent.mkdir(parents=True)
        lsp_path.write_text("{}")

        self._build(entry, repo_path, al_lsp=False)

        assert not lsp_path.exists()

    @pytest.mark.usefixtures("artifact_paths")
    def test_returns_true_when_enabled(self, entry, repo_path):
        assert self._build(entry, repo_path, al_lsp=True) is True

    @pytest.mark.usefixtures("artifact_paths")
    def test_writes_project_lsp_config(self, entry, repo_path):
        self._build(entry, repo_path, al_lsp=True)

        config = self._read(repo_path)
        assert "lspServers" in config
        assert "altool" in config["lspServers"]

    @pytest.mark.usefixtures("artifact_paths")
    def test_command_is_unqualified_al(self, entry, repo_path):
        self._build(entry, repo_path, al_lsp=True)

        # Copilot CLI silently rejects absolute command paths — must resolve via PATH.
        assert self._read(repo_path)["lspServers"]["altool"]["command"] == "al"

    @pytest.mark.usefixtures("artifact_paths")
    def test_al_file_extension_registered(self, entry, repo_path):
        self._build(entry, repo_path, al_lsp=True)

        assert self._read(repo_path)["lspServers"]["altool"]["fileExtensions"] == {".al": "al"}

    @pytest.mark.usefixtures("artifact_paths")
    def test_project_paths_inserted_after_launchlspserver(self, entry, repo_path):
        self._build(entry, repo_path, al_lsp=True)

        args = self._read(repo_path)["lspServers"]["altool"]["args"]
        launch_idx = args.index("launchlspserver")
        assert args[launch_idx + 1] == str(repo_path / "src/App")
        assert args[launch_idx + 2] == str(repo_path / "src/TestApp")

    @pytest.mark.usefixtures("artifact_paths")
    def test_artifact_cache_paths_used_for_package_cache(self, entry, repo_path):
        self._build(entry, repo_path, al_lsp=True)

        args = self._read(repo_path)["lspServers"]["altool"]["args"]
        cache_idx = args.index("--packagecachepath")
        probing_idx = args.index("--assemblyprobingpaths")
        assert args[cache_idx + 1 : probing_idx] == ["C:/cache/w1/Extensions", "C:/cache/platform/Applications"]

    @pytest.mark.usefixtures("artifact_paths")
    def test_does_not_require_container_when_artifacts_present(self, entry, repo_path):
        assert self._build(entry, repo_path, al_lsp=True, container_name="") is True

    @pytest.mark.usefixtures("no_artifacts")
    def test_uses_container_compiler_folder_when_present(self, entry, repo_path, tmp_path):
        compiler_root = tmp_path / "compiler" / "test-container"
        (compiler_root / "symbols").mkdir(parents=True)
        with patch(
            "bcbench.agent.shared.lsp.compiler_symbol_folder_for_container",
            return_value=(compiler_root, compiler_root / "symbols"),
        ):
            assert self._build(entry, repo_path, al_lsp=True, container_name="test-container") is True

        args = self._read(repo_path)["lspServers"]["altool"]["args"]
        cache_idx = args.index("--packagecachepath")
        assert args[cache_idx + 1] == str(compiler_root / "symbols")

    @pytest.mark.usefixtures("artifact_paths")
    def test_container_compiler_folder_wins_over_artifact_cache(self, entry, repo_path, tmp_path):
        compiler_root = tmp_path / "compiler" / "test-container"
        (compiler_root / "symbols").mkdir(parents=True)
        with patch(
            "bcbench.agent.shared.lsp.compiler_symbol_folder_for_container",
            return_value=(compiler_root, compiler_root / "symbols"),
        ):
            self._build(entry, repo_path, al_lsp=True, container_name="test-container")

        args = self._read(repo_path)["lspServers"]["altool"]["args"]
        cache_idx = args.index("--packagecachepath")
        end_idx = args.index("--assemblyprobingpaths") if "--assemblyprobingpaths" in args else len(args)
        assert args[cache_idx + 1 : end_idx] == [str(compiler_root / "symbols")]

    @pytest.mark.usefixtures("no_artifacts")
    def test_raises_with_download_hint_when_neither_source_available(self, entry, repo_path):
        with pytest.raises(AgentError, match=r"Download-BCSymbols\.ps1"):
            self._build(entry, repo_path, al_lsp=True, container_name="")


class TestClaudeLspPlugin:
    @staticmethod
    def _plugin_dir(repo_path: Path) -> Path:
        return repo_path / ".claude" / "plugins" / "al-lsp"

    @staticmethod
    def _read_lsp(repo_path: Path) -> dict:
        return json.loads((TestClaudeLspPlugin._plugin_dir(repo_path) / ".lsp.json").read_text(encoding="utf-8"))

    @staticmethod
    def _read_manifest(repo_path: Path) -> dict:
        return json.loads((TestClaudeLspPlugin._plugin_dir(repo_path) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))

    @staticmethod
    def _build(entry, repo_path, **kwargs):
        return build_claude_lsp_plugin(entry, EvaluationCategory.BUG_FIX, repo_path, **kwargs)

    def test_returns_none_when_disabled(self, entry, repo_path):
        assert self._build(entry, repo_path, al_lsp=False) is None
        assert not self._plugin_dir(repo_path).exists()

    def test_removes_stale_plugin_when_disabled(self, entry, repo_path):
        plugin_dir = self._plugin_dir(repo_path)
        (plugin_dir / ".claude-plugin").mkdir(parents=True)
        (plugin_dir / ".claude-plugin" / "plugin.json").write_text("{}")
        (plugin_dir / ".lsp.json").write_text("{}")

        self._build(entry, repo_path, al_lsp=False)

        assert not plugin_dir.exists()

    @pytest.mark.usefixtures("artifact_paths")
    def test_returns_plugin_dir_when_enabled(self, entry, repo_path):
        plugin_dir = self._build(entry, repo_path, al_lsp=True)
        assert plugin_dir == self._plugin_dir(repo_path)

    @pytest.mark.usefixtures("artifact_paths")
    def test_writes_minimal_manifest(self, entry, repo_path):
        self._build(entry, repo_path, al_lsp=True)

        manifest = self._read_manifest(repo_path)
        assert manifest["name"] == "al-lsp"  # the only required field per Claude plugin docs

    @pytest.mark.usefixtures("artifact_paths")
    def test_writes_lsp_config_at_plugin_root(self, entry, repo_path):
        self._build(entry, repo_path, al_lsp=True)

        config = self._read_lsp(repo_path)
        # Claude's schema: top-level server name (no `lspServers` wrapper, unlike Copilot).
        assert "altool" in config
        assert "lspServers" not in config

    @pytest.mark.usefixtures("artifact_paths")
    def test_extension_to_language_uses_claude_schema(self, entry, repo_path):
        self._build(entry, repo_path, al_lsp=True)

        # Claude uses `extensionToLanguage`; Copilot uses `fileExtensions`.
        server = self._read_lsp(repo_path)["altool"]
        assert server["extensionToLanguage"] == {".al": "al"}
        assert "fileExtensions" not in server

    @pytest.mark.usefixtures("artifact_paths")
    def test_command_is_unqualified_al(self, entry, repo_path):
        self._build(entry, repo_path, al_lsp=True)

        assert self._read_lsp(repo_path)["altool"]["command"] == "al"

    @pytest.mark.usefixtures("artifact_paths")
    def test_project_paths_inserted_after_launchlspserver(self, entry, repo_path):
        self._build(entry, repo_path, al_lsp=True)

        args = self._read_lsp(repo_path)["altool"]["args"]
        launch_idx = args.index("launchlspserver")
        assert args[launch_idx + 1] == str(repo_path / "src/App")
        assert args[launch_idx + 2] == str(repo_path / "src/TestApp")

    @pytest.mark.usefixtures("no_artifacts")
    def test_uses_container_compiler_folder_when_present(self, entry, repo_path, tmp_path):
        compiler_root = tmp_path / "compiler" / "test-container"
        (compiler_root / "symbols").mkdir(parents=True)
        with patch(
            "bcbench.agent.shared.lsp.compiler_symbol_folder_for_container",
            return_value=(compiler_root, compiler_root / "symbols"),
        ):
            assert self._build(entry, repo_path, al_lsp=True, container_name="test-container") is not None

        args = self._read_lsp(repo_path)["altool"]["args"]
        cache_idx = args.index("--packagecachepath")
        assert args[cache_idx + 1] == str(compiler_root / "symbols")

    @pytest.mark.usefixtures("no_artifacts")
    def test_raises_with_download_hint_when_neither_source_available(self, entry, repo_path):
        with pytest.raises(AgentError, match=r"Download-BCSymbols\.ps1"):
            self._build(entry, repo_path, al_lsp=True, container_name="")
