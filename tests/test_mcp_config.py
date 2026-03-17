import json
from pathlib import Path

import pytest

from bcbench.agent.shared.mcp import _build_assembly_probing_paths, build_mcp_config
from tests.conftest import create_dataset_entry


def _make_config(*servers: dict) -> dict:
    return {"mcp": {"servers": list(servers)}}


ALTOOL_SERVER = {
    "name": "altool",
    "type": "stdio",
    "command": "al",
    "args": ["launchmcpserver", "--transport", "stdio"],
}

MSLEARN_SERVER = {
    "name": "mslearn",
    "type": "http",
    "url": "https://learn.microsoft.com/api/mcp",
}


@pytest.fixture()
def entry():
    return create_dataset_entry(project_paths=["src/App", "src/TestApp"])


@pytest.fixture()
def repo_path() -> Path:
    return Path("/repo")


class TestAlMcpProjectPaths:
    def test_project_paths_inserted_after_launchmcpserver(self, entry, repo_path):
        config = _make_config(ALTOOL_SERVER)

        config_json, _ = build_mcp_config(config, entry, repo_path, al_mcp=True)
        assert config_json is not None

        parsed = json.loads(config_json)
        args = parsed["mcpServers"]["altool"]["args"]
        launch_idx = args.index("launchmcpserver")
        assert args[launch_idx + 1] == str(repo_path / "src/App")
        assert args[launch_idx + 2] == str(repo_path / "src/TestApp")

    def test_transport_stdio_is_present(self, entry, repo_path):
        config = _make_config(ALTOOL_SERVER)

        config_json, _ = build_mcp_config(config, entry, repo_path, al_mcp=True)
        assert config_json is not None

        args = json.loads(config_json)["mcpServers"]["altool"]["args"]
        transport_idx = args.index("--transport")
        assert args[transport_idx + 1] == "stdio"

    def test_altool_excluded_when_al_mcp_disabled(self, entry, repo_path):
        config = _make_config(ALTOOL_SERVER)

        result = build_mcp_config(config, entry, repo_path, al_mcp=False)

        assert result == (None, None)

    def test_altool_excluded_but_other_servers_kept(self, entry, repo_path):
        config = _make_config(ALTOOL_SERVER, MSLEARN_SERVER)

        config_json, names = build_mcp_config(config, entry, repo_path, al_mcp=False)
        assert config_json is not None
        assert names is not None

        parsed = json.loads(config_json)
        assert "altool" not in parsed["mcpServers"]
        assert "mslearn" in parsed["mcpServers"]
        assert names == ["mslearn"]

    def test_returns_server_names(self, entry, repo_path):
        config = _make_config(ALTOOL_SERVER, MSLEARN_SERVER)

        _, names = build_mcp_config(config, entry, repo_path, al_mcp=True)
        assert names is not None

        assert set(names) == {"altool", "mslearn"}


class TestBuildAssemblyProbingPaths:
    def test_nonexistent_compiler_folder_has_no_dlls(self, tmp_path):
        result = _build_assembly_probing_paths(tmp_path / "nonexistent")
        assert not any("dlls" in p for p in result)

    def test_includes_dlls_folder(self, tmp_path):
        (tmp_path / "dlls").mkdir()

        result = _build_assembly_probing_paths(tmp_path)

        assert str(tmp_path / "dlls") in result

    def test_shared_folder_suppresses_system_dotnet(self, tmp_path):
        dlls = tmp_path / "dlls"
        dlls.mkdir()
        (dlls / "shared").mkdir()

        result = _build_assembly_probing_paths(tmp_path)

        assert not any("Program Files" in p for p in result)

    def test_returns_list(self, tmp_path):
        (tmp_path / "dlls").mkdir()

        result = _build_assembly_probing_paths(tmp_path)

        assert isinstance(result, list)
