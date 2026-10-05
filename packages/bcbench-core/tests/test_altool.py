from pathlib import Path

import pytest

from bcbench_core import altool
from bcbench_core.altool import build_assembly_probing_paths as _build_assembly_probing_paths
from bcbench_core.container import ContainerConfig


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


@pytest.fixture
def dotnet_shared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shared = tmp_path / "dotnet" / "shared"
    monkeypatch.setattr(altool, "_DOTNET_SHARED", shared)
    return shared


def _install_runtime(shared: Path, version: str, *, aspnetcore: bool = True) -> None:
    (shared / "Microsoft.NETCore.App" / version).mkdir(parents=True)
    if aspnetcore:
        (shared / "Microsoft.AspNetCore.App" / version).mkdir(parents=True)


class TestDotnetRuntimeDetection:
    def test_none_without_dotnet(self, dotnet_shared):
        assert altool._detect_dotnet_runtime_version() is None
        assert altool._dotnet_runtime_probing_paths() == []

    def test_picks_newest_runtime_with_matching_aspnetcore_excluding_unstable_majors(self, dotnet_shared):
        _install_runtime(dotnet_shared, "8.0.11")
        _install_runtime(dotnet_shared, "8.0.20", aspnetcore=False)
        _install_runtime(dotnet_shared, "9.0.1")
        _install_runtime(dotnet_shared, "not-a-version")
        (dotnet_shared / "Microsoft.NETCore.App" / "README.txt").write_text("x")

        assert str(altool._detect_dotnet_runtime_version()) == "8.0.11"
        assert altool._dotnet_runtime_probing_paths() == [
            str(dotnet_shared / "Microsoft.NETCore.App" / "8.0.11"),
            str(dotnet_shared / "Microsoft.AspNetCore.App" / "8.0.11"),
        ]


def test_compiler_symbol_folder_defaults_to_bccontainerhelper(tmp_path):
    assert altool.compiler_symbol_folder_for_container("bc") == (altool.DEFAULT_COMPILER_ROOT / "bc", altool.DEFAULT_COMPILER_ROOT / "bc" / "symbols")
    assert altool.compiler_symbol_folder_for_container("bc", tmp_path) == (tmp_path / "bc", tmp_path / "bc" / "symbols")


class TestResolveArtifactLspPaths:
    def test_none_without_downloaded_artifact(self, tmp_path):
        assert altool.resolve_artifact_lsp_paths("27.2", artifacts_cache=tmp_path) is None

    def test_none_without_symbol_folders(self, tmp_path):
        (tmp_path / "sandbox" / "27.2.1.0").mkdir(parents=True)

        assert altool.resolve_artifact_lsp_paths("27.2", artifacts_cache=tmp_path) is None

    def test_country_and_platform_paths(self, tmp_path, dotnet_shared):
        root = tmp_path / "sandbox" / "27.2.1.0"
        (root / "w1" / "Extensions").mkdir(parents=True)
        (root / "platform" / "Applications").mkdir(parents=True)
        _install_runtime(dotnet_shared, "8.0.11")

        resolved = altool.resolve_artifact_lsp_paths("27.2", artifacts_cache=tmp_path)

        assert resolved is not None
        package_cache_paths, probing_paths = resolved

        assert package_cache_paths == [str(root / "w1" / "Extensions"), str(root / "platform" / "Applications")]
        assert probing_paths[0] == str(root / "platform")
        assert probing_paths[1:] == altool._dotnet_runtime_probing_paths()


class TestResolveSymbolPaths:
    def test_prefers_container_compiler_folder(self, tmp_path):
        compiler = tmp_path / "compiler"
        (compiler / "bc" / "symbols").mkdir(parents=True)
        (compiler / "bc" / "dlls" / "shared").mkdir(parents=True)
        (tmp_path / "cache" / "sandbox" / "27.2.1.0" / "w1" / "Extensions").mkdir(parents=True)

        assert altool.resolve_symbol_paths("bc", "27.2", compiler_root=compiler, artifacts_cache=tmp_path / "cache") == (
            [str(compiler / "bc" / "symbols")],
            [str(compiler / "bc" / "dlls" / "shared"), str(compiler / "bc" / "dlls")],
        )

    def test_falls_back_to_artifact_cache(self, tmp_path, dotnet_shared):
        extensions = tmp_path / "cache" / "sandbox" / "27.2.1.0" / "w1" / "Extensions"
        extensions.mkdir(parents=True)

        resolved = altool.resolve_symbol_paths("bc", "27.2", compiler_root=tmp_path / "compiler", artifacts_cache=tmp_path / "cache")

        assert resolved == ([str(extensions)], [])

    def test_none_without_symbols(self, tmp_path):
        assert altool.resolve_symbol_paths("bc", "27.2", compiler_root=tmp_path / "compiler", artifacts_cache=tmp_path / "cache") is None


@pytest.mark.parametrize(
    ("probing_paths", "expected"),
    [
        ([], ["launchlspserver", "app", "test", "--packagecachepath", "cache"]),
        (["dlls"], ["launchlspserver", "app", "test", "--packagecachepath", "cache", "--assemblyprobingpaths", "dlls"]),
    ],
)
def test_build_lsp_args_puts_projects_before_options(probing_paths, expected):
    assert altool.build_lsp_args(["app", "test"], ["cache"], probing_paths) == expected


def test_connection_env_omits_empty_values():
    container = ContainerConfig("bc", "admin", "", "CRONUS", server_url="http://bc")

    assert altool.connection_env(container) == {"BC_SERVER_URL": "http://bc", "BC_SERVER_USERNAME": "admin"}
