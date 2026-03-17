import json
import shutil
from pathlib import Path
from typing import Any

from jinja2 import Template
from packaging.version import Version

from bcbench.dataset import DatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)

# .NET major versions excluded from runtime detection (unstable/preview)
# See: navcontainerhelper/InitializeModule.ps1 line 62
_EXCLUDED_DOTNET_MAJORS = {9, 10}
_DOTNET_SHARED = Path(r"C:\Program Files\dotnet\shared")


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


def _build_assembly_probing_paths(compiler_folder: Path) -> list[str]:
    """Build list of assembly probing paths for the AL compiler.

    The AL compiler recursively searches subdirectories (AssemblyLocatorBase.cs uses
    SearchOption.AllDirectories), so a single ``dlls`` entry covers Service, OpenXML,
    Mock Assemblies, etc. System .NET runtime paths must be added separately since
    they live outside the compiler folder.

    Each path must be a separate CLI argument (System.CommandLine with
    AllowMultipleArgumentsPerToken expects space-separated values, NOT semicolons).
    """
    paths: list[str] = []
    dlls_path = compiler_folder / "dlls"

    if dlls_path.is_dir():
        paths.append(str(dlls_path))

    # .NET runtime: needed for BaseApp's DotNet interop types.
    # If New-BcCompilerFolder bundled a shared\ folder (dotnet < minimum), it's already
    # covered by the recursive dlls\ search above. Otherwise, add system dotnet paths.
    shared_folder = dlls_path / "shared"
    if not shared_folder.is_dir():
        dotnet_version = _detect_dotnet_runtime_version()
        if dotnet_version:
            paths.append(str(_DOTNET_SHARED / "Microsoft.NETCore.App" / str(dotnet_version)))
            paths.append(str(_DOTNET_SHARED / "Microsoft.AspNetCore.App" / str(dotnet_version)))
            logger.info(f"Using system .NET runtime {dotnet_version} for assembly probing")
        else:
            logger.warning("No compatible .NET runtime found. DotNet interop types may not resolve.")

    return paths


def _build_server_entry(server: dict[str, Any], template_context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    server_type: str = server["type"]
    server_name: str = server["name"]

    match server_type:
        case "http":
            return server_name, {
                "type": server_type,
                "url": server["url"],
            }
        case "stdio":
            args: list[str] = server["args"]
            rendered_args = [Template(arg).render(**template_context) for arg in args]
            command: str = shutil.which(server["command"]) or server["command"]
            return server_name, {
                "type": server_type,
                "command": command,
                "args": rendered_args,
            }
        case _:
            logger.error(f"Unsupported MCP server type: {server_type}, {server}")
            raise AgentError(f"Unsupported MCP server type: {server_type}")


def build_mcp_config(config: dict[str, Any], entry: DatasetEntry, repo_path: Path, al_mcp: bool = False, container_name: str = "bcbench") -> tuple[str | None, list[str] | None]:
    mcp_servers: list[dict[str, Any]] = config.get("mcp", {}).get("servers", [])

    if al_mcp:  # insert project paths right after "launchmcpserver" (positional args must precede options)
        al_server = next(s for s in mcp_servers if s["name"] == "altool")
        insert_idx = al_server["args"].index("launchmcpserver") + 1
        project_paths = [str(repo_path / p) for p in entry.project_paths]
        al_server["args"][insert_idx:insert_idx] = project_paths
        logger.info("AL MCP server enabled")
    else:
        mcp_servers = list(filter(lambda s: s.get("name") != "altool", mcp_servers))

    if not mcp_servers:
        return None, None

    compiler_folder = Path(r"C:\ProgramData\BcContainerHelper\compiler") / container_name
    symbols_path = str(compiler_folder / "symbols")
    assembly_probing_paths = _build_assembly_probing_paths(compiler_folder)

    if al_mcp:
        al_server = next(s for s in mcp_servers if s["name"] == "altool")

        # Each path must be a separate arg (System.CommandLine expects space-separated values)
        if assembly_probing_paths:
            al_server["args"].extend(["--assemblyprobingpaths", *assembly_probing_paths])
            logger.info(f"Assembly probing paths: {assembly_probing_paths}")

    template_context: dict[str, str | Path] = {"repo_path": repo_path, "package_cache_path": symbols_path}
    mcp_server_names: list[str] = [server["name"] for server in mcp_servers]
    mcp_config = {"mcpServers": dict(map(lambda s: _build_server_entry(s, template_context), mcp_servers))}

    logger.info(f"Using MCP servers: {mcp_server_names}")
    if not (compiler_folder / "dlls").exists():
        logger.warning(f"Compiler folder not found: {compiler_folder}. Run New-BCCompilerFolderSync to create it.")
    logger.debug(f"MCP configuration: {json.dumps(mcp_config, indent=2)}")

    return json.dumps(mcp_config, separators=(",", ":")), mcp_server_names
