import subprocess
from typing import Any

from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)


def _plugin_name(spec: str) -> str:
    return spec.split("@", 1)[0]


def install_plugins(config: dict[str, Any], copilot_cmd: str) -> list[str] | None:
    plugins: dict[str, Any] = config.get("plugins", {})
    marketplaces: list[str] = plugins.get("marketplaces") or []
    specs: list[str] = plugins.get("install") or []

    if not specs:
        return None

    for marketplace in marketplaces:
        logger.info(f"Registering plugin marketplace: {marketplace}")
        _run([copilot_cmd, "plugin", "marketplace", "add", marketplace])

    for spec in specs:
        logger.info(f"Installing plugin: {spec}")
        _run([copilot_cmd, "plugin", "install", spec])

    plugin_names = [_plugin_name(spec) for spec in specs]
    logger.info(f"Installed plugins: {plugin_names}")
    return plugin_names


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AgentError(f"Plugin command failed: {' '.join(cmd)}\n{result.stderr}")
