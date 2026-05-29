import json
from copy import deepcopy
from pathlib import Path

import pytest

from bcbench.agent.shared.mcp import _build_assembly_probing_paths, _set_runtime_version, build_mcp_config
from tests.conftest import create_dataset_entry


def _make_config(*servers: dict) -> dict:
    return {"mcp": {"servers": [deepcopy(s) for s in servers]}}


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


@pytest.fixture
def entry():
    return create_dataset_entry(project_paths=["src/App", "src/TestApp"])


@pytest.fixture
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


class TestAltoolEnvForwarding:
    _MANAGED_VARS = (
        "BC_SERVER_URL",
        "BC_SERVER_INSTANCE",
        "BC_SERVER_USERNAME",
        "BC_SERVER_PASSWORD",
    )

    @pytest.fixture(autouse=True)
    def _isolate_env(self):
        import os

        saved = {var: os.environ.pop(var, None) for var in self._MANAGED_VARS}
        yield
        for var in self._MANAGED_VARS:
            os.environ.pop(var, None)
            value = saved[var]
            if value is not None:
                os.environ[var] = value

    def test_forwards_set_bc_server_vars(self, entry, repo_path, monkeypatch):
        monkeypatch.setenv("BC_SERVER_URL", "http://bcbench-210528")
        monkeypatch.setenv("BC_SERVER_INSTANCE", "BC")
        monkeypatch.setenv("BC_SERVER_USERNAME", "admin")
        monkeypatch.setenv("BC_SERVER_PASSWORD", "secret")

        config_json, _ = build_mcp_config(_make_config(ALTOOL_SERVER), entry, repo_path, al_mcp=True)
        assert config_json is not None

        env = json.loads(config_json)["mcpServers"]["altool"]["env"]
        assert env == {
            "BC_SERVER_URL": "http://bcbench-210528",
            "BC_SERVER_INSTANCE": "BC",
            "BC_SERVER_PASSWORD": "secret",
            "BC_SERVER_USERNAME": "admin",
        }

    def test_omits_env_block_when_no_vars_set(self, entry, repo_path):
        config_json, _ = build_mcp_config(_make_config(ALTOOL_SERVER), entry, repo_path, al_mcp=True)
        assert config_json is not None

        assert "env" not in json.loads(config_json)["mcpServers"]["altool"]

    def test_skips_empty_string_values(self, entry, repo_path, monkeypatch):
        monkeypatch.setenv("BC_SERVER_USERNAME", "admin")
        monkeypatch.setenv("BC_SERVER_PASSWORD", "")

        config_json, _ = build_mcp_config(_make_config(ALTOOL_SERVER), entry, repo_path, al_mcp=True)
        assert config_json is not None

        env = json.loads(config_json)["mcpServers"]["altool"]["env"]
        assert env == {"BC_SERVER_USERNAME": "admin"}

    def test_does_not_forward_to_other_stdio_servers(self, entry, repo_path, monkeypatch):
        monkeypatch.setenv("BC_SERVER_USERNAME", "admin")
        other_stdio = {
            "name": "filesystem",
            "type": "stdio",
            "command": "node",
            "args": ["server.js"],
        }

        config_json, _ = build_mcp_config(_make_config(ALTOOL_SERVER, other_stdio), entry, repo_path, al_mcp=True)
        assert config_json is not None

        parsed = json.loads(config_json)["mcpServers"]
        assert "env" not in parsed["filesystem"]
        assert parsed["altool"]["env"] == {"BC_SERVER_USERNAME": "admin"}


class TestBuildAssemblyProbingPaths:
    def test_nonexistent_compiler_folder_has_no_dlls(self, tmp_path):
        result = _build_assembly_probing_paths(tmp_path / "nonexistent")
        assert not any("dlls" in p for p in result)

    def test_includes_dlls_folder(self, tmp_path):
        (tmp_path / "dlls").mkdir()

        result = _build_assembly_probing_paths(tmp_path)

        assert str(tmp_path / "dlls") in result

    def test_dlls_after_dotnet(self, tmp_path):
        (tmp_path / "dlls").mkdir()

        result = _build_assembly_probing_paths(tmp_path)

        dlls_idx = next(i for i, p in enumerate(result) if "dlls" in p)
        assert dlls_idx == len(result) - 1

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


class TestSetRuntimeVersion:
    def test_sets_runtime_from_platform(self, tmp_path):
        app_json = {"platform": "25.0.0.0", "version": "25.0.0.0"}
        (tmp_path / "app.json").write_text(json.dumps(app_json))

        _set_runtime_version([str(tmp_path)])

        result = json.loads((tmp_path / "app.json").read_text())
        assert result["runtime"] == "14.0"

    def test_skips_when_runtime_already_set(self, tmp_path):
        app_json = {"platform": "25.0.0.0", "runtime": "12.0"}
        (tmp_path / "app.json").write_text(json.dumps(app_json))

        _set_runtime_version([str(tmp_path)])

        result = json.loads((tmp_path / "app.json").read_text())
        assert result["runtime"] == "12.0"

    def test_platform_27_maps_to_runtime_16(self, tmp_path):
        app_json = {"platform": "27.0.0.0"}
        (tmp_path / "app.json").write_text(json.dumps(app_json))

        _set_runtime_version([str(tmp_path)])

        result = json.loads((tmp_path / "app.json").read_text())
        assert result["runtime"] == "16.0"

    def test_skips_missing_app_json(self, tmp_path):
        _set_runtime_version([str(tmp_path)])  # should not raise
