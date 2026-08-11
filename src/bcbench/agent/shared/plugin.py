import json
import shutil
from collections.abc import Mapping
from pathlib import Path

from bcbench.config import get_config
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.operations.git_operations import clone_repo_at_revision
from bcbench.types import PluginConfig

logger = get_logger(__name__)
_config = get_config()


def write_agent_plugin(folder: str, manifest: Mapping[str, object], files: Mapping[str, object]) -> Path:
    """Write a plugin folder and return its path.

    Args:
        folder: Directory name under the plugin root.
        manifest: Manifest written to ``.claude-plugin/plugin.json``.
        files: Plugin-relative paths mapped to JSON-serializable content.

    Returns:
        The plugin directory path for ``--plugin-dir``.
    """
    plugin_dir: Path = _config.paths.plugin_root / folder

    (plugin_dir / _config.file_patterns.plugin_manifest.parent).mkdir(parents=True, exist_ok=True)
    (plugin_dir / _config.file_patterns.plugin_manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for rel_path, content in files.items():
        target: Path = plugin_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(content, indent=2), encoding="utf-8")

    logger.info(f"Wrote agent plugin '{folder}': {plugin_dir}")
    return plugin_dir


def remove_agent_plugin(folder: str) -> None:
    plugin_dir = _config.paths.plugin_root / folder
    if plugin_dir.exists():
        shutil.rmtree(plugin_dir)
        logger.info(f"Removed stale agent plugin '{folder}': {plugin_dir}")


def resolve_config_plugins(agent_config: dict, *, allow_copilot_manifest: bool = False) -> list[tuple[PluginConfig, Path]]:
    """Resolve the config's enabled plugin entries to loadable plugin folders.

    A plugin is either `local` (an absolute path on this machine) or `github` (cloned from its repo
    at a pinned revision into the plugin root).

    Resolved folders are handed to the CLI as ``--plugin-dir`` and so are loaded for a single session only.

    Args:
        agent_config: Parsed `config.yaml`.
        allow_copilot_manifest: Also accept a root ``plugin.json`` - a layout only Copilot CLI loads.

    Returns:
        Each enabled plugin, in config order, paired with the folder it resolved to.

    Raises:
        AgentError: If two enabled plugins share a name, or a plugin does not resolve to a folder
            holding a plugin manifest.
    """
    plugins = [PluginConfig(**entry) for entry in agent_config["plugins"] if entry.get("enabled", False)]

    # A GitHub plugin clones into ``<plugin_root>/<name>`` and every plugin is recorded as
    # ``<name>@<revision|source>``, so two enabled plugins sharing a name would clobber each other's
    # clone and collide on their record. There is no reason to enable the same-named plugin twice, so
    # reject duplicate names up front.
    names = [plugin.name for plugin in plugins]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise AgentError(f"Duplicate plugin name(s) among enabled plugins: {', '.join(duplicates)}")

    return [(plugin, _resolve_plugin(plugin, allow_copilot_manifest)) for plugin in plugins]


def _has_plugin_manifest(plugin_dir: Path, allow_copilot_manifest: bool) -> bool:
    """True if the folder holds a plugin manifest in a location the target agent can load.

    Claude Code loads only ``.claude-plugin/plugin.json``. GitHub Copilot CLI loads that layout too
    but also accepts a ``plugin.json`` at the plugin root, so a root-only manifest is honored only
    when ``allow_copilot_manifest`` is set (Copilot runs) - never for a Claude run, which would otherwise
    forward the plugin via ``--plugin-dir`` only for Claude to ignore it.
    """
    if (plugin_dir / _config.file_patterns.plugin_manifest).is_file():
        return True
    return allow_copilot_manifest and (plugin_dir / _config.file_patterns.plugin_manifest.name).is_file()


def _resolve_plugin(plugin: PluginConfig, allow_copilot_manifest: bool) -> Path:
    match plugin.source:
        case "local":
            plugin_dir = Path(plugin.path).expanduser().resolve()
        case "github":
            clone_dir: Path = _clone_dir(plugin)
            clone_repo_at_revision(str(plugin.repo), str(plugin.revision), clone_dir)
            plugin_dir = _plugin_dir_in_clone(clone_dir, plugin)

    if not _has_plugin_manifest(plugin_dir, allow_copilot_manifest):
        nested: Path = plugin_dir / _config.file_patterns.plugin_manifest
        locations: str = f"{nested} or {plugin_dir / _config.file_patterns.plugin_manifest.name}" if allow_copilot_manifest else str(nested)
        raise AgentError(f"Plugin '{plugin.name}' has no manifest at {locations}")

    logger.info(f"Loading plugin {plugin.record} from {plugin_dir}")
    return plugin_dir


def _clone_dir(plugin: PluginConfig) -> Path:
    """Resolve the clone destination, rejecting names that escape the plugin root."""
    plugin_root: Path = _config.paths.plugin_root.resolve()
    clone_dir: Path = (plugin_root / plugin.name).resolve()
    if clone_dir.parent != plugin_root:
        raise AgentError(f"Plugin '{plugin.name}': name must be a single directory directly under {plugin_root}")
    return clone_dir


def _plugin_dir_in_clone(clone_dir: Path, plugin: PluginConfig) -> Path:
    """Resolve the plugin folder inside its clone, rejecting paths that escape the clone."""
    plugin_dir: Path = (clone_dir / plugin.path).resolve()
    if not plugin_dir.is_relative_to(clone_dir):
        raise AgentError(f"Plugin '{plugin.name}': path '{plugin.path}' resolves outside its clone at {clone_dir}")
    return plugin_dir
