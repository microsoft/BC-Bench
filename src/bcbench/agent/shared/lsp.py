import json
from pathlib import Path

from bcbench.agent.shared.altool_paths import (
    build_assembly_probing_paths,
    compiler_symbol_folder_for_container,
    resolve_artifact_lsp_paths,
    set_runtime_version,
)
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)

_COPILOT_LSP_RELATIVE_PATH = Path(".github") / "lsp.json"
_CLAUDE_PLUGIN_RELATIVE_PATH = Path(".claude") / "plugins" / "al-lsp"


def _resolve_symbol_paths(entry: BaseDatasetEntry, category: EvaluationCategory, container_name: str) -> tuple[list[str], list[str]]:
    """Resolve (package_cache_paths, assembly_probing_paths) for the LSP server.

    Prefers the container's compiler folder when available — its single flat layout is the exact same arg shape AL-MCP uses.
    Falls back to the raw BC artifact cache for container-free local runs. Raises a clear error pointing at the symbol-download script when neither is present.
    """
    if container_name:
        compiler_folder, symbols_folder = compiler_symbol_folder_for_container(container_name)
        if symbols_folder.is_dir():
            logger.info(f"Using container compiler-folder symbols: {symbols_folder}")
            return [str(symbols_folder)], build_assembly_probing_paths(compiler_folder)

    artifact_paths = resolve_artifact_lsp_paths(entry.environment_setup_version)
    if artifact_paths is not None:
        package_cache_paths, assembly_probing_paths = artifact_paths
        logger.info(f"Using BC artifact cache symbols for v{entry.environment_setup_version}: {package_cache_paths}")
        return package_cache_paths, assembly_probing_paths

    raise AgentError(
        f"No AL symbols found for BC v{entry.environment_setup_version}. Run `./scripts/Download-BCSymbols.ps1 -Category {category} -InstanceId {entry.instance_id}` (no container required) and retry."
    )


def _build_lsp_args(project_paths: list[str], package_cache_paths: list[str], assembly_probing_paths: list[str]) -> list[str]:
    # `launchlspserver [<projects>...] [options]` — projects come first as positional args.
    args: list[str] = ["launchlspserver", *project_paths, "--packagecachepath", *package_cache_paths]
    if assembly_probing_paths:
        args.extend(["--assemblyprobingpaths", *assembly_probing_paths])
    return args


def _prepare_lsp(entry: BaseDatasetEntry, category: EvaluationCategory, repo_path: Path, container_name: str) -> list[str]:
    """Common preparation shared by both agent variants: set runtime, resolve symbols, build args."""
    project_paths = [str(repo_path / p) for p in entry.project_paths]
    set_runtime_version(project_paths)
    package_cache_paths, assembly_probing_paths = _resolve_symbol_paths(entry, category, container_name)
    return _build_lsp_args(project_paths, package_cache_paths, assembly_probing_paths)


def build_copilot_lsp_config(entry: BaseDatasetEntry, category: EvaluationCategory, repo_path: Path, al_lsp: bool, container_name: str = "") -> bool:
    """Write Copilot CLI's project-level LSP config to <repo_path>/.github/lsp.json.

    Copilot CLI auto-discovers ``.github/lsp.json`` on session start — no CLI flag needed.
    Removes any stale config when ``al_lsp=False`` so toggling the flag off actually disables the server.
    """
    lsp_config_path = repo_path / _COPILOT_LSP_RELATIVE_PATH

    if not al_lsp:
        if lsp_config_path.is_file():
            lsp_config_path.unlink()
            logger.info(f"Removed stale LSP config: {lsp_config_path}")
        return False

    args = _prepare_lsp(entry, category, repo_path, container_name)

    # Copilot CLI resolves `command` via PATH (absolute paths are silently rejected with
    # "Server <name> is configured but not available"). `al` is the published altool
    # wrapper installed via the .NET tool — it must be on PATH.
    lsp_config = {
        "lspServers": {
            "altool": {
                "command": "al",
                "args": args,
                "fileExtensions": {".al": "al"},
            }
        }
    }

    lsp_config_path.parent.mkdir(parents=True, exist_ok=True)
    lsp_config_path.write_text(json.dumps(lsp_config, indent=2), encoding="utf-8")

    logger.info(f"Wrote Copilot LSP config: {lsp_config_path}")
    logger.debug(f"LSP configuration: {json.dumps(lsp_config, indent=2)}")

    return True


def build_claude_lsp_plugin(entry: BaseDatasetEntry, category: EvaluationCategory, repo_path: Path, al_lsp: bool, container_name: str = "") -> Path | None:
    """Build a per-task Claude Code plugin folder containing the AL LSP server.

    Claude Code surfaces LSP servers through its plugin system. ``claude --plugin-dir <path>``
    loads a plugin for a single session with no marketplace registration, no
    ``ENABLE_LSP_TOOL`` global state, and no cross-run plugin leakage — the same
    per-task isolation the Copilot side gets from ``.github/lsp.json``.

    Layout written under ``<repo>/.claude/plugins/al-lsp/``:
        .claude-plugin/plugin.json   — minimal manifest (only ``name`` is required)
        .lsp.json                    — LSP server config in Claude's schema

    Returns the plugin folder path so the caller can pass it as ``--plugin-dir``,
    or None when disabled.
    """
    plugin_dir = repo_path / _CLAUDE_PLUGIN_RELATIVE_PATH

    if not al_lsp:
        if plugin_dir.exists():
            for p in sorted(plugin_dir.rglob("*"), reverse=True):
                p.rmdir() if p.is_dir() else p.unlink()
            plugin_dir.rmdir()
            logger.info(f"Removed stale Claude LSP plugin: {plugin_dir}")
        return None

    args = _prepare_lsp(entry, category, repo_path, container_name)

    # Minimal plugin manifest. Name is the only required field; we don't ship skills/agents/hooks.
    plugin_manifest = {
        "name": "al-lsp",
        "version": "1.0.0",
        "description": "AL Language Server for Business Central agentic development",
    }
    # Claude's LSP schema differs from Copilot's: no `lspServers` wrapper, and uses
    # `extensionToLanguage` instead of `fileExtensions`.
    lsp_config = {
        "altool": {
            "command": "al",
            "args": args,
            "extensionToLanguage": {".al": "al"},
        }
    }

    (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps(plugin_manifest, indent=2), encoding="utf-8")
    (plugin_dir / ".lsp.json").write_text(json.dumps(lsp_config, indent=2), encoding="utf-8")

    logger.info(f"Wrote Claude LSP plugin: {plugin_dir}")
    logger.debug(f"LSP configuration: {json.dumps(lsp_config, indent=2)}")

    return plugin_dir
