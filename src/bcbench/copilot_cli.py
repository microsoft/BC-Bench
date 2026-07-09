"""Shared helper for locating the GitHub Copilot CLI executable."""

import shutil

__all__ = ["find_copilot"]


def find_copilot() -> str | None:
    # Prefer copilot.exe over copilot.bat/copilot.cmd shims on Windows: the .bat shim invokes
    # PowerShell, which re-parses arguments and corrupts prompts containing double quotes.
    return shutil.which("copilot.exe") or shutil.which("copilot.cmd") or shutil.which("copilot")
