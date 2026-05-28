from pathlib import Path

from bcbench.agent.shared.altool_paths import (
    build_assembly_probing_paths,
    compiler_symbol_folder_for_container,
    resolve_artifact_lsp_paths,
    set_runtime_version,
)
from bcbench.agent.shared.plugin import remove_agent_plugin, write_agent_plugin
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.types import AgentType, EvaluationCategory

logger = get_logger(__name__)

_AL_LSP_PLUGIN_FOLDER = "al-lsp-plugin"
_AL_LSP_MANIFEST = {"name": "al-lsp"}


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
        f"No AL symbols found for BC v{entry.environment_setup_version}. Run `./scripts/Download-BCSymbols.ps1 -Category {category.value} -InstanceId {entry.instance_id}` (no container required) and retry."
    )


def _build_lsp_args(project_paths: list[str], package_cache_paths: list[str], assembly_probing_paths: list[str]) -> list[str]:
    # `launchlspserver [<projects>...] [options]` — projects come first as positional args.
    args: list[str] = ["launchlspserver", *project_paths, "--packagecachepath", *package_cache_paths]
    if assembly_probing_paths:
        args.extend(["--assemblyprobingpaths", *assembly_probing_paths])
    return args


def _lsp_config_for(agent_type: AgentType, args: list[str]) -> dict:
    """Build the agent-specific `.lsp.json` content.

    Both agents launch the same `al launchlspserver` process — only the surrounding LSP-routing schema differs:

    - Copilot CLI expects `{ "lspServers": { name: { ..., "fileExtensions": {".ext": "lang"} } } }`
    - Claude Code expects `{ name: { ..., "extensionToLanguage": {".ext": "lang"} } }` (no wrapper, different extension key)

    `command: "al"` is unqualified by design: Copilot CLI silently rejects absolute paths in LSP
    `command` ("Server <name> is configured but not available"), so the published `altool` wrapper
    (`al`) must resolve via PATH on both sides.
    """
    server = {"command": "al", "args": args}
    match agent_type:
        case AgentType.COPILOT:
            return {"lspServers": {"altool": {**server, "fileExtensions": {".al": "al"}}}}
        case AgentType.CLAUDE:
            return {"altool": {**server, "extensionToLanguage": {".al": "al"}}}


def build_al_lsp_plugin(entry: BaseDatasetEntry, category: EvaluationCategory, repo_path: Path, agent_type: AgentType, al_lsp: bool, container_name: str = "") -> Path | None:
    """Build a per-task AL-LSP plugin folder, return its path or None.

    Loaded by both Copilot CLI and Claude Code via ``--plugin-dir <path>`` for a single
    session — no marketplace registration, no global state, no cross-run plugin leakage.
    Folder layout is identical between agents; only the LSP-routing schema in
    ``.lsp.json`` differs (see :func:`_lsp_config_for`).
    """
    if not al_lsp:
        remove_agent_plugin(repo_path, _AL_LSP_PLUGIN_FOLDER)
        return None

    project_paths = [str(repo_path / p) for p in entry.project_paths]
    set_runtime_version(project_paths)
    package_cache_paths, assembly_probing_paths = _resolve_symbol_paths(entry, category, container_name)
    args = _build_lsp_args(project_paths, package_cache_paths, assembly_probing_paths)
    lsp_config = _lsp_config_for(agent_type, args)

    plugin_dir = write_agent_plugin(repo_path, _AL_LSP_PLUGIN_FOLDER, _AL_LSP_MANIFEST, {".lsp.json": lsp_config})
    logger.debug(f"AL LSP configuration for {agent_type.value}: {lsp_config}")
    return plugin_dir
