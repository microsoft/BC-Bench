"""Launch support for `altool`, the AL compiler and language tooling: symbol paths, arguments, and connection settings.

Both `altool launchmcpserver` and `altool launchlspserver` need the same package-cache layout and assembly probing paths.
"""

import logging
from pathlib import Path

from packaging.version import InvalidVersion, Version

from bcbench_core.artifacts import DEFAULT_ARTIFACTS_CACHE, resolve_artifact_version_root
from bcbench_core.container import ContainerConfig

logger = logging.getLogger(__name__)

# .NET major versions excluded from runtime detection (unstable/preview)
# See: navcontainerhelper/InitializeModule.ps1 line 62
_EXCLUDED_DOTNET_MAJORS = {9, 10}
_DOTNET_SHARED = Path(r"C:\Program Files\dotnet\shared")
# BcContainerHelper's default compiler folder root, one subfolder per container
DEFAULT_COMPILER_ROOT = Path(r"C:\ProgramData\BcContainerHelper\compiler")


def _detect_dotnet_runtime_version() -> Version | None:
    dotnet_shared = _DOTNET_SHARED
    netcore_folder = dotnet_shared / "Microsoft.NETCore.App"
    aspnetcore_folder = dotnet_shared / "Microsoft.AspNetCore.App"

    if not netcore_folder.is_dir():
        return None

    versions: list[Version] = []
    for entry in netcore_folder.iterdir():
        if not entry.is_dir() or not (aspnetcore_folder / entry.name).is_dir():
            continue
        try:
            v = Version(entry.name)
            if v.major not in _EXCLUDED_DOTNET_MAJORS:
                versions.append(v)
        except InvalidVersion:
            continue

    return max(versions) if versions else None


def _dotnet_runtime_probing_paths() -> list[str]:
    """Probing paths for the latest compatible system .NET runtime (empty if none found)."""
    dotnet_version = _detect_dotnet_runtime_version()
    if not dotnet_version:
        logger.warning("No compatible .NET runtime found. DotNet interop types may not resolve.")
        return []

    logger.info(f"Using system .NET runtime {dotnet_version} for assembly probing")
    return [
        str(_DOTNET_SHARED / "Microsoft.NETCore.App" / str(dotnet_version)),
        str(_DOTNET_SHARED / "Microsoft.AspNetCore.App" / str(dotnet_version)),
    ]


def build_assembly_probing_paths(compiler_folder: Path) -> list[str]:
    """Build list of assembly probing paths for the AL compiler.

    The AL compiler recursively searches subdirectories (AssemblyLocatorBase.cs uses
    SearchOption.AllDirectories), so a single ``dlls`` entry covers Service, OpenXML,
    Mock Assemblies, etc. System .NET runtime paths must be added separately since
    they live outside the compiler folder.

    Path order matters: .NET runtime paths must come BEFORE dlls to avoid stale
    type-forwarding stubs (e.g. XrmV91's 5.0.0.0 DLLs) shadowing the real types.
    This matches BCContainerHelper's ordering (OpenXML → dotnet → Service).

    Each path must be a separate CLI argument (System.CommandLine with
    AllowMultipleArgumentsPerToken expects space-separated values, NOT semicolons).
    """
    paths: list[str] = []
    dlls_path = compiler_folder / "dlls"

    # .NET runtime paths first — avoids stale type-forwarding stubs in dlls\ subfolders
    shared_folder = dlls_path / "shared"
    if shared_folder.is_dir():
        paths.append(str(shared_folder))
    else:
        paths.extend(_dotnet_runtime_probing_paths())

    # dlls\ after dotnet — recursively covers Service, OpenXML, Mock Assemblies, etc.
    if dlls_path.is_dir():
        paths.append(str(dlls_path))

    return paths


def compiler_symbol_folder_for_container(container_name: str, compiler_root: Path = DEFAULT_COMPILER_ROOT) -> tuple[Path, Path]:
    """Return the BCContainerHelper compiler and symbol folder for a given container."""
    folder = compiler_root / container_name
    return folder, folder / "symbols"


def resolve_artifact_lsp_paths(environment_setup_version: str, country: str = "w1", artifacts_cache: Path = DEFAULT_ARTIFACTS_CACHE) -> tuple[list[str], list[str]] | None:
    """Resolve (package_cache_paths, assembly_probing_paths) from the BC artifact cache.

    BCContainerHelper's `Download-Artifacts` lands the artifact under
    ``<artifacts_cache>\\sandbox\\<full-version>\\``; see `resolve_artifact_version_root`
    for how a major.minor version (e.g. "27.2") is matched.

    Returns None when the artifact has not been downloaded yet — caller should fall
    back or surface an actionable error.
    """
    version_root = resolve_artifact_version_root(environment_setup_version, artifacts_cache)
    if version_root is None:
        return None

    # Country-specific app symbols (e.g. w1 BaseApp), then platform symbols (System app etc.)
    package_cache_paths = [str(p) for p in (version_root / country / "Extensions", version_root / "platform" / "Applications") if p.is_dir()]
    if not package_cache_paths:
        return None

    # platform/ alone — the AL compiler recursively scans `--assemblyprobingpaths`
    # (SearchOption.AllDirectories), so a single root covers ServiceTier, Test Assemblies, etc.
    platform_dir = version_root / "platform"
    assembly_probing_paths: list[str] = [str(platform_dir)] if platform_dir.is_dir() else []

    # System .NET runtime — same fallback as the container-derived path so DotNet interop types resolve even without BC-shipped reference assemblies.
    assembly_probing_paths.extend(_dotnet_runtime_probing_paths())

    return package_cache_paths, assembly_probing_paths


def resolve_symbol_paths(
    container_name: str, version: str, country: str = "w1", compiler_root: Path = DEFAULT_COMPILER_ROOT, artifacts_cache: Path = DEFAULT_ARTIFACTS_CACHE
) -> tuple[list[str], list[str]] | None:
    """Resolve (package_cache_paths, assembly_probing_paths) for altool.

    Prefers the container's compiler folder when available, then falls back to the BC artifact cache.
    Returns None when neither has symbols.
    """
    compiler_folder, symbols_folder = compiler_symbol_folder_for_container(container_name, compiler_root)
    if symbols_folder.is_dir():
        logger.info(f"Using container compiler-folder symbols: {symbols_folder}")
        return [str(symbols_folder)], build_assembly_probing_paths(compiler_folder)

    artifact_paths = resolve_artifact_lsp_paths(version, country, artifacts_cache)
    if artifact_paths is not None:
        logger.info(f"Using BC artifact cache symbols for v{version}: {artifact_paths[0]}")
    return artifact_paths


def build_lsp_args(project_paths: list[str], package_cache_paths: list[str], assembly_probing_paths: list[str]) -> list[str]:
    # `launchlspserver [<projects>...] [options]` — projects come first as positional args.
    args: list[str] = ["launchlspserver", *project_paths, "--packagecachepath", *package_cache_paths]
    if assembly_probing_paths:
        args.extend(["--assemblyprobingpaths", *assembly_probing_paths])
    return args


def connection_env(container: ContainerConfig) -> dict[str, str]:
    """Environment variables altool reads to connect to a BC server; empty values are omitted."""
    return {
        key: value
        for key, value in {
            "BC_SERVER_URL": container.server_url,
            "BC_SERVER_INSTANCE": container.server_instance,
            "BC_SERVER_USERNAME": container.username,
            "BC_SERVER_PASSWORD": container.password,
        }.items()
        if value
    }
