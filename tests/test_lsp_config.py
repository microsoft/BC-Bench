import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.shared.lsp import build_lsp_config
from bcbench.exceptions import AgentError
from bcbench.types import EvaluationCategory
from tests.conftest import create_dataset_entry


@pytest.fixture
def entry():
    return create_dataset_entry(project_paths=["src/App", "src/TestApp"])


@pytest.fixture
def repo_path(tmp_path) -> Path:
    return tmp_path / "repo"


def _read_lsp(repo_path: Path) -> dict:
    return json.loads((repo_path / ".github" / "lsp.json").read_text(encoding="utf-8"))


def _build(entry, repo_path, **kwargs):
    return build_lsp_config(entry, EvaluationCategory.BUG_FIX, repo_path, **kwargs)


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


class TestBuildLspConfig:
    def test_returns_false_when_disabled(self, entry, repo_path):
        result = _build(entry, repo_path, al_lsp=False)
        assert result is False
        assert not (repo_path / ".github" / "lsp.json").exists()

    def test_removes_stale_config_when_disabled(self, entry, repo_path):
        lsp_path = repo_path / ".github" / "lsp.json"
        lsp_path.parent.mkdir(parents=True)
        lsp_path.write_text("{}")

        _build(entry, repo_path, al_lsp=False)

        assert not lsp_path.exists()

    @pytest.mark.usefixtures("artifact_paths")
    def test_returns_true_when_enabled(self, entry, repo_path):
        assert _build(entry, repo_path, al_lsp=True) is True

    @pytest.mark.usefixtures("artifact_paths")
    def test_writes_project_lsp_config(self, entry, repo_path):
        _build(entry, repo_path, al_lsp=True)

        config = _read_lsp(repo_path)
        assert "lspServers" in config
        assert "altool" in config["lspServers"]

    @pytest.mark.usefixtures("artifact_paths")
    def test_command_is_unqualified_al(self, entry, repo_path):
        _build(entry, repo_path, al_lsp=True)

        server = _read_lsp(repo_path)["lspServers"]["altool"]
        # Copilot CLI silently rejects absolute command paths — must resolve via PATH.
        assert server["command"] == "al"

    @pytest.mark.usefixtures("artifact_paths")
    def test_al_file_extension_registered(self, entry, repo_path):
        _build(entry, repo_path, al_lsp=True)

        server = _read_lsp(repo_path)["lspServers"]["altool"]
        assert server["fileExtensions"] == {".al": "al"}

    @pytest.mark.usefixtures("artifact_paths")
    def test_project_paths_inserted_after_launchlspserver(self, entry, repo_path):
        _build(entry, repo_path, al_lsp=True)

        args = _read_lsp(repo_path)["lspServers"]["altool"]["args"]
        launch_idx = args.index("launchlspserver")
        assert args[launch_idx + 1] == str(repo_path / "src/App")
        assert args[launch_idx + 2] == str(repo_path / "src/TestApp")

    @pytest.mark.usefixtures("artifact_paths")
    def test_artifact_cache_paths_used_for_package_cache(self, entry, repo_path):
        _build(entry, repo_path, al_lsp=True)

        args = _read_lsp(repo_path)["lspServers"]["altool"]["args"]
        cache_idx = args.index("--packagecachepath")
        probing_idx = args.index("--assemblyprobingpaths")
        # All entries between --packagecachepath and --assemblyprobingpaths are package paths.
        assert args[cache_idx + 1 : probing_idx] == ["C:/cache/w1/Extensions", "C:/cache/platform/Applications"]

    @pytest.mark.usefixtures("artifact_paths")
    def test_does_not_require_container_when_artifacts_present(self, entry, repo_path):
        # No container_name supplied — should still succeed via artifact cache.
        assert _build(entry, repo_path, al_lsp=True, container_name="") is True

    @pytest.mark.usefixtures("no_artifacts")
    def test_uses_container_compiler_folder_when_present(self, entry, repo_path, tmp_path):
        compiler_root = tmp_path / "compiler" / "test-container"
        (compiler_root / "symbols").mkdir(parents=True)
        with patch(
            "bcbench.agent.shared.lsp.compiler_symbol_folder_for_container",
            return_value=(compiler_root, compiler_root / "symbols"),
        ):
            result = _build(entry, repo_path, al_lsp=True, container_name="test-container")

        assert result is True
        args = _read_lsp(repo_path)["lspServers"]["altool"]["args"]
        cache_idx = args.index("--packagecachepath")
        assert args[cache_idx + 1] == str(compiler_root / "symbols")

    @pytest.mark.usefixtures("artifact_paths")
    def test_container_compiler_folder_wins_over_artifact_cache(self, entry, repo_path, tmp_path):
        # When BOTH sources exist, the container compiler folder must win — same
        # arg shape as AL-MCP, easier to debug a "which symbols set is this?" question.
        compiler_root = tmp_path / "compiler" / "test-container"
        (compiler_root / "symbols").mkdir(parents=True)
        with patch(
            "bcbench.agent.shared.lsp.compiler_symbol_folder_for_container",
            return_value=(compiler_root, compiler_root / "symbols"),
        ):
            _build(entry, repo_path, al_lsp=True, container_name="test-container")

        args = _read_lsp(repo_path)["lspServers"]["altool"]["args"]
        cache_idx = args.index("--packagecachepath")
        # Probing paths may be absent when neither dlls/ nor system .NET is found — slice to end-of-list in that case.
        end_idx = args.index("--assemblyprobingpaths") if "--assemblyprobingpaths" in args else len(args)
        assert args[cache_idx + 1 : end_idx] == [str(compiler_root / "symbols")]  # single path, not the 2-path artifact-cache layout

    @pytest.mark.usefixtures("no_artifacts")
    def test_raises_with_download_hint_when_neither_source_available(self, entry, repo_path):
        with pytest.raises(AgentError, match=r"Download-BCSymbols\.ps1"):
            _build(entry, repo_path, al_lsp=True, container_name="")
