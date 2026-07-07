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
        case _:
            raise AgentError(f"Unknown plugin source: {source!r}")
