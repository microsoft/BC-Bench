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

# Offset from BC platform major version to AL runtime version.
# E.g. platform 25.0 (BC 2024w2) → runtime 14.0, platform 27.0 → runtime 16.0
# See: BC-DeveloperExperience RuntimeVersion.cs
_PLATFORM_TO_RUNTIME_OFFSET = 11


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


def _set_runtime_version(project_paths: list[str]) -> None:
    """Set the AL runtime version in each project's app.json based on platform version.

    The AL MCP compiler (altool 17.0+) defaults to the latest runtime when "runtime"
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

    if not al_mcp:
        mcp_servers = list(filter(lambda s: s.get("name") != "altool", mcp_servers))

    if not mcp_servers:
        return None, None

    template_context: dict[str, str | Path] = {"repo_path": repo_path}

    if al_mcp:
        compiler_folder = Path(r"C:\ProgramData\BcContainerHelper\compiler") / container_name
        template_context["package_cache_path"] = str(compiler_folder / "symbols")

        al_server = next(s for s in mcp_servers if s["name"] == "altool")
        project_paths = [str(repo_path / p) for p in entry.project_paths]

        # Insert project paths right after "launchmcpserver" (positional args must precede options)
        insert_idx: int = al_server["args"].index("launchmcpserver") + 1
        al_server["args"][insert_idx:insert_idx] = project_paths

        _set_runtime_version(project_paths)

        # Each path must be a separate arg (System.CommandLine expects space-separated values)
        assembly_probing_paths = _build_assembly_probing_paths(compiler_folder)
        if assembly_probing_paths:
            al_server["args"].extend(["--assemblyprobingpaths", *assembly_probing_paths])
            logger.info(f"Assembly probing paths: {assembly_probing_paths}")

    mcp_server_names: list[str] = [server["name"] for server in mcp_servers]
    mcp_config = {"mcpServers": dict(map(lambda s: _build_server_entry(s, template_context), mcp_servers))}

    logger.info(f"Using MCP servers: {mcp_server_names}")
    logger.debug(f"MCP configuration: {json.dumps(mcp_config, indent=2)}")

    return json.dumps(mcp_config, separators=(",", ":")), mcp_server_names
