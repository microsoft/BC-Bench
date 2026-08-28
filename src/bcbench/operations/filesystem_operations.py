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


def clear_directory(path: Path) -> None:
    """
    Remove everything inside a directory, leaving the directory itself in place.

    Use instead of `remove_tree` when the directory should survive.
    """
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_dir():
            remove_tree(child)
        else:
            child.chmod(stat.S_IWRITE)
            child.unlink()


def prepare_run_dir(output_dir: Path, run_id: str) -> Path:
    """Prepare a directory for a run, removing any existing contents."""
    run_dir = output_dir / run_id
    if run_dir.exists():
        remove_tree(run_dir)
    run_dir.mkdir(parents=True)
    return run_dir
