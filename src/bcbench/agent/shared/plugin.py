import json
import shutil
from pathlib import Path

from bcbench.logger import get_logger

logger = get_logger(__name__)

# Both Copilot CLI and Claude Code accept `--plugin-dir <path>` (repeatable) for ad-hoc plugin loading, and both look for the manifest at `.claude-plugin/plugin.json`
# We keep plugins under `.bcbench/` to avoid colliding with agent-reserved dirs (`.claude/`, `.github/`)
_PLUGIN_ROOT = Path(".bcbench")


def _plugin_dir_for(repo_path: Path, folder: str) -> Path:
    return repo_path / _PLUGIN_ROOT / folder


def write_agent_plugin(repo_path: Path, folder: str, manifest: dict, files: dict[str, dict]) -> Path:
    """Write a plugin folder and return its path.

    Args:
        repo_path: Repository root.
        folder: Directory name under ``<repo>/.bcbench/``.
        manifest: Manifest written to ``.claude-plugin/plugin.json``.
        files: Plugin-relative paths mapped to JSON-serializable content.

    Returns:
        The plugin directory path for ``--plugin-dir``.
    """
    plugin_dir = _plugin_dir_for(repo_path, folder)

    (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for rel_path, content in files.items():
        target = plugin_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(content, indent=2), encoding="utf-8")

    logger.info(f"Wrote agent plugin '{folder}': {plugin_dir}")
    return plugin_dir


def remove_agent_plugin(repo_path: Path, folder: str) -> None:
    plugin_dir = _plugin_dir_for(repo_path, folder)
    if plugin_dir.exists():
        shutil.rmtree(plugin_dir)
        logger.info(f"Removed stale agent plugin '{folder}': {plugin_dir}")
