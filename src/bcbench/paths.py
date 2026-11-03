"""Locations of files shipped inside the bcbench package."""

from pathlib import Path

AGENT_SHARE_DIR = Path(__file__).parent / "agent" / "shared"
SHARED_CONFIG_FILE = AGENT_SHARE_DIR / "config.yaml"
