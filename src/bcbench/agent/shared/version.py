import re
import subprocess

from bcbench.exceptions import AgentError


def get_cli_version(command: str | None, name: str) -> str:
    if command is None:
        raise AgentError(f"{name} not found in PATH. Please ensure it is installed and available.")
    try:
        result = subprocess.run([command, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AgentError(f"Could not determine {name} version: {exc}") from exc
    match = re.search(r"\b\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\b", result.stdout)
    if match is None:
        raise AgentError(f"Unrecognized {name} version output: {result.stdout!r}")
    return match.group()
