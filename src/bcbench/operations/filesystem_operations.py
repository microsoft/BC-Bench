"""Filesystem operations."""

import shutil
import stat
from collections.abc import Callable
from pathlib import Path


def _force_remove_readonly(func: Callable[[str], object], path: str, _: BaseException) -> None:
    Path(path).chmod(stat.S_IWRITE)
    func(path)


def remove_tree(path: Path) -> None:
    """
    Remove a directory tree, even if it contains read-only files on Windows.

    Use when `shutil.rmtree` fails due to read-only files, which usually occur in secondary runs on Windows.
    """
    shutil.rmtree(path, onexc=_force_remove_readonly)
