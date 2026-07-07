"""Install agent plugins (marketplace or local) declared in config, via the CLI's plugin commands.

Config injection (`extraKnownMarketplaces` / `enabledPlugins`) is trust-dialog-gated and ignored in
headless mode, so we drive the CLI's real `plugin marketplace add` + `plugin install` commands.
Because the plugin store is user-scope/global and execution-based categories run entries as a
parallel matrix on a shared self-hosted runner, each entry installs into a fresh per-entry config
home (`COPILOT_HOME` / `CLAUDE_CONFIG_DIR`) under `<repo>/.bcbench/`, which the runner also applies
to the agent launch. Marketplace content is cloned at its pinned commit into `<repo>/.bcbench/plugins/`.

NOTE: do NOT import from `bcbench.agent.*` here — `bcbench.agent.__init__` imports the runners,
which import `bcbench.operations`; importing agent from operations would create a cycle.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from shutil import copytree, rmtree

from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger
from bcbench.operations.git_operations import clone_at_commit
from bcbench.operations.instruction_operations import _get_source_instructions_path
from bcbench.types import AgentType

logger = get_logger(__name__)

_BCBENCH_ROOT = ".bcbench"
_PLUGINS_FOLDER = "plugins"  # under <repo>/.bcbench/plugins/
_MARKETPLACE_MANIFESTS = (".claude-plugin/marketplace.json", ".github/plugin/marketplace.json")


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text).strip("-")


def _read_marketplace_name(marketplace_dir: Path) -> str:
    for rel in _MARKETPLACE_MANIFESTS:
        manifest = marketplace_dir / rel
        if manifest.is_file():
            name = json.loads(manifest.read_text(encoding="utf-8")).get("name")
            if name:
                return name
    raise AgentError(f"No marketplace.json with a 'name' found under {marketplace_dir}")


def _materialize(entry_cfg: dict, entry: BaseDatasetEntry, plugins_root: Path) -> tuple[Path, str]:
    """Clone (marketplace) or copy (local) the marketplace into plugins_root.

    Returns:
        (marketplace_dir, record_suffix) where record_suffix is the pinned commit or "local".
    """
    source = entry_cfg["source"]
    match source:
        case "marketplace":
            repo: str = entry_cfg["repo"]
            commit: str = entry_cfg["commit"]
            dest = plugins_root / _slug(repo)
            if dest.exists():
                rmtree(dest)
            clone_at_commit(repo, commit, dest)
            return dest, commit
        case "local":
            rel_path: str = entry_cfg["path"]
            src = _get_source_instructions_path(entry.repo) / rel_path
            if not src.is_dir():
                raise AgentError(f"Local plugin marketplace not found: {src}")
            dest = plugins_root / _slug(rel_path)
            if dest.exists():
                rmtree(dest)
            copytree(src, dest)
            return dest, "local"
    raise AgentError(f"Unknown plugin source: {source!r}")


def _home_env_var(agent_type: AgentType) -> str:
    match agent_type:
        case AgentType.COPILOT:
            return "COPILOT_HOME"
        case AgentType.CLAUDE:
            return "CLAUDE_CONFIG_DIR"
    raise AgentError(f"Unsupported agent type for plugins: {agent_type}")


def _run_plugin_cmd(cli_cmd: str, args: list[str], env: dict[str, str]) -> None:
    subprocess.run([cli_cmd, "plugin", *args], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)


def _validate_entry(entry_cfg: dict) -> None:
    source = entry_cfg.get("source")
    match source:
        case "marketplace":
            required = ("repo", "commit", "plugins")
        case "local":
            required = ("path", "plugins")
        case _:
            raise AgentError(f"Unknown plugin source: {source!r}")
    missing = [key for key in required if key not in entry_cfg]
    if missing:
        raise AgentError(f"Plugin entry {entry_cfg!r} is missing required key(s): {missing}")


def setup_plugins_from_config(agent_config: dict, entry: BaseDatasetEntry, repo_path: Path, agent_type: AgentType, cli_cmd: str) -> tuple[list[str], dict[str, str]]:
    """Install every enabled plugin entry into a fresh per-entry CLI config home.

    Returns (plugin_records, env_overrides). env_overrides sets the isolated config home
    (COPILOT_HOME / CLAUDE_CONFIG_DIR) that the runner must also apply to the agent launch, so
    concurrent matrix entries never share the user-scope plugin store. Returns ([], {}) when no
    entry is enabled. Raises AgentError on failure, removing the partial home.
    """
    entries = [e for e in (agent_config.get("plugins") or []) if e.get("enabled", True)]
    if not entries:
        return [], {}

    bcbench_dir = repo_path / _BCBENCH_ROOT
    plugins_root = bcbench_dir / _PLUGINS_FOLDER
    home = bcbench_dir / f"{agent_type.value}-home"
    for path in (plugins_root, home):
        if path.exists():
            rmtree(path)  # clean-before
        path.mkdir(parents=True, exist_ok=True)

    home_var = _home_env_var(agent_type)
    env = {**os.environ, home_var: str(home)}
    records: list[str] = []
    try:
        for entry_cfg in entries:
            _validate_entry(entry_cfg)
            marketplace_dir, record_suffix = _materialize(entry_cfg, entry, plugins_root)
            marketplace_name = _read_marketplace_name(marketplace_dir)
            _run_plugin_cmd(cli_cmd, ["marketplace", "add", str(marketplace_dir)], env)
            for plugin in entry_cfg["plugins"]:
                _run_plugin_cmd(cli_cmd, ["install", f"{plugin}@{marketplace_name}"], env)
                records.append(f"{plugin}@{record_suffix}")
                logger.info(f"Installed plugin {plugin}@{marketplace_name} into {home}")
    except (subprocess.CalledProcessError, OSError) as e:
        if home.exists():
            rmtree(home)
        raise AgentError(f"Plugin setup failed: {e}") from e
    except AgentError:
        if home.exists():
            rmtree(home)
        raise

    return records, {home_var: str(home)}
