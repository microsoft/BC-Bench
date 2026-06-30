import subprocess
import tempfile
from typing import Any

from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)


def _marketplace_url(repo: str) -> str:
    return repo if "://" in repo else f"https://github.com/{repo}.git"


def _plugin_name(spec: str) -> str:
    return spec.split("@", 1)[0]


def _clone_marketplace_at_sha(repo: str, sha: str) -> str:
    clone_dir = tempfile.mkdtemp(prefix="bcbench-plugin-")
    url = _marketplace_url(repo)
    logger.info(f"Cloning marketplace {url} at {sha} into {clone_dir}")
    _run(["git", "clone", "--quiet", url, clone_dir])
    _run(["git", "-C", clone_dir, "checkout", "--quiet", sha])
    return clone_dir


def install_plugins(config: dict[str, Any], cli_cmd: str) -> list[str] | None:
    """Install Copilot/Claude plugins declared in config, pinned to a specific marketplace SHA.

    Each entry under `plugins.install` must provide `repo` (marketplace OWNER/REPO or git URL),
    `sha` (commit to pin the marketplace to), and `name` (`<plugin>@<marketplace>` install spec).
    The marketplace is cloned at the pinned SHA and added locally before installing, so no
    marketplace is assumed to be registered by default.

    Returns:
        Installed plugin names, or None when no plugins are configured.
    """
    specs: list[dict[str, str]] = config.get("plugins", {}).get("install") or []

    if not specs:
        return None

    plugin_names: list[str] = []
    for spec in specs:
        repo, sha, name = spec["repo"], spec["sha"], spec["name"]
        marketplace_dir = _clone_marketplace_at_sha(repo, sha)

        logger.info(f"Registering marketplace from {marketplace_dir}")
        _run([cli_cmd, "plugin", "marketplace", "add", marketplace_dir])

        logger.info(f"Installing plugin: {name}")
        _run([cli_cmd, "plugin", "install", name])

        plugin_names.append(_plugin_name(name))

    logger.info(f"Installed plugins: {plugin_names}")
    return plugin_names


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AgentError(f"Plugin command failed: {' '.join(cmd)}\n{result.stderr}")
