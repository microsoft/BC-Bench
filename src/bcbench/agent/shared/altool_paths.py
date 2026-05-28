"""Shared altool helpers used by both AL-MCP and AL-LSP integrations.

Both `altool launchmcpserver` and `altool launchlspserver` need the same
package-cache layout, assembly probing paths, and runtime-version handling.
"""

import json
from pathlib import Path

from packaging.version import Version

from bcbench.logger import get_logger

logger = get_logger(__name__)

# .NET major versions excluded from runtime detection (unstable/preview)
# See: navcontainerhelper/InitializeModule.ps1 line 62
_EXCLUDED_DOTNET_MAJORS = {9, 10}
_DOTNET_SHARED = Path(r"C:\Program Files\dotnet\shared")

# Offset from BC platform major version to AL runtime version.
# E.g. platform 25.0 (BC 2024w2) → runtime 14.0, platform 27.0 → runtime 16.0
# See: BC-DeveloperExperience RuntimeVersion.cs
_PLATFORM_TO_RUNTIME_OFFSET = 11

# Default location of BCContainerHelper-downloaded artifacts (symbols, reference assemblies, etc.)
_BCARTIFACTS_CACHE = Path(r"C:\bcartifacts.cache")


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
        except Exception:
            continue

    return max(versions) if versions else None


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
        dotnet_version = _detect_dotnet_runtime_version()
        if dotnet_version:
            paths.append(str(_DOTNET_SHARED / "Microsoft.NETCore.App" / str(dotnet_version)))
            paths.append(str(_DOTNET_SHARED / "Microsoft.AspNetCore.App" / str(dotnet_version)))
            logger.info(f"Using system .NET runtime {dotnet_version} for assembly probing")
        else:
            logger.warning("No compatible .NET runtime found. DotNet interop types may not resolve.")

    # dlls\ after dotnet — recursively covers Service, OpenXML, Mock Assemblies, etc.
    if dlls_path.is_dir():
        paths.append(str(dlls_path))

    return paths


def set_runtime_version(project_paths: list[str]) -> None:
    """Set the AL runtime version in each project's app.json based on platform version.

    The AL compiler (altool 17.0+) defaults to the latest runtime when "runtime"
    is not set in app.json, enabling newer validation rules that reject older code.
    Setting the runtime to match the platform version makes the compiler behave
    like the version that originally compiled the code.
    """
    for project_path in project_paths:
        app_json_path = Path(project_path) / "app.json"
        if not app_json_path.is_file():
            continue

        try:
            app_json = json.loads(app_json_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            continue

        if app_json.get("runtime"):
            continue

        platform = app_json.get("platform", "")
        try:
            platform_major = int(platform.split(".")[0])
        except (ValueError, IndexError):
            continue

        runtime_major = platform_major - _PLATFORM_TO_RUNTIME_OFFSET
        if runtime_major < 1:
            continue

        runtime = f"{runtime_major}.0"
        app_json["runtime"] = runtime
        app_json_path.write_text(json.dumps(app_json, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Set runtime={runtime} in {app_json_path} (platform {platform})")


def compiler_symbol_folder_for_container(container_name: str) -> tuple[Path, Path]:
    """Return the BCContainerHelper compiler and symbol folder for a given container."""
    folder = Path(r"C:\ProgramData\BcContainerHelper\compiler") / container_name
    return folder, folder / "symbols"


def resolve_artifact_lsp_paths(environment_setup_version: str, country: str = "w1") -> tuple[list[str], list[str]] | None:
    """Resolve (package_cache_paths, assembly_probing_paths) from the BC artifact cache.

    BCContainerHelper's `Download-Artifacts` (driven by `scripts/Download-BCSymbols.ps1`
    or by the CI container setup) lands the artifact under
    ``C:\\bcartifacts.cache\\sandbox\\<full-version>\\``. The dataset's
    ``environment_setup_version`` is major.minor (e.g. "27.2"); BCContainerHelper
    expands that to a full ``<major>.<minor>.<build>.<revision>``. We glob the cache
    for matching versions, lexically sort, and pick the newest — BC's full-version
    fields are constant-width in practice, so a lexical sort matches a numeric one.

    Returns None when the artifact has not been downloaded yet — caller should fall
    back or surface an actionable error.
    """
    version_roots = sorted((_BCARTIFACTS_CACHE / "sandbox").glob(f"{environment_setup_version}.*"))
    if not version_roots:
        return None
    version_root = version_roots[-1]  # newest revision

    # Country-specific app symbols (e.g. W1 BaseApp), then platform symbols (System app etc.)
    package_cache_paths = [str(p) for p in (version_root / country / "Extensions", version_root / "platform" / "Applications") if p.is_dir()]
    if not package_cache_paths:
        return None

    # platform/ alone — the AL compiler recursively scans `--assemblyprobingpaths`
    # (SearchOption.AllDirectories), so a single root covers ServiceTier, Test Assemblies, etc.
    platform_dir = version_root / "platform"
    assembly_probing_paths = [str(platform_dir)] if platform_dir.is_dir() else []

    # System .NET runtime — same fallback as the container-derived path so DotNet
    # interop types resolve even without BC-shipped reference assemblies.
    dotnet_version = _detect_dotnet_runtime_version()
    if dotnet_version:
        assembly_probing_paths.append(str(_DOTNET_SHARED / "Microsoft.NETCore.App" / str(dotnet_version)))
        assembly_probing_paths.append(str(_DOTNET_SHARED / "Microsoft.AspNetCore.App" / str(dotnet_version)))

    return package_cache_paths, assembly_probing_paths
