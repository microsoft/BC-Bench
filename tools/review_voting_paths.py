"""Strict snapshot metadata and Windows-compatible filesystem operations."""

import hashlib
import os
import shutil
import stat
from pathlib import Path
from typing import Any


def filesystem_path(path: Path) -> Path:
    absolute = os.path.abspath(path)  # noqa: PTH100 - normalize lexically before any potentially failing Windows filesystem resolution
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return Path(absolute)
    return Path("\\\\?\\UNC\\" + absolute[2:] if absolute.startswith("\\\\") else "\\\\?\\" + absolute)


def snapshot_files(root: Path) -> list[tuple[str, Path]]:
    base = filesystem_path(root)
    root_stat = base.lstat()
    if not stat.S_ISDIR(root_stat.st_mode) or getattr(root_stat, "st_file_attributes", 0) & 0x400:
        raise ValueError("Snapshot root must be a real directory, not a reparse point")
    files = []
    pending = [(base, "")]
    while pending:
        directory, prefix = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name == ".git":
                    continue
                relative = prefix + entry.name
                # Do not use is_file/is_dir: they can hide inaccessible entries.
                info = entry.stat(follow_symlinks=False)
                if getattr(info, "st_file_attributes", 0) & 0x400 or stat.S_ISLNK(info.st_mode):
                    raise ValueError(f"Snapshot contains a link/reparse point: {relative}")
                if stat.S_ISDIR(info.st_mode):
                    pending.append((Path(entry.path), relative + "/"))
                elif stat.S_ISREG(info.st_mode):
                    files.append((relative, Path(entry.path)))
                else:
                    raise ValueError(f"Unsupported snapshot entry: {relative}")
    return sorted(files)


def snapshot_inventory(root: Path) -> dict[str, dict[str, Any]]:
    inventory = {}
    for relative, path in snapshot_files(root):
        before = path.stat()
        sha256 = hashlib.sha256()
        git_blob = hashlib.sha1(usedforsecurity=False)
        git_blob.update(f"blob {before.st_size}\0".encode())
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                sha256.update(chunk)
                git_blob.update(chunk)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(f"Snapshot changed while hashing: {relative}")
        inventory[relative] = {"bytes": before.st_size, "sha256": sha256.hexdigest(), "git_blob": git_blob.hexdigest()}
    return inventory


def copy_tree(source: Path, destination: Path, *, exclude_git: bool = False) -> None:
    # Long paths are an OS addressing concern, not a way around content policy.
    # No file contents are decoded or injected into a prompt here.
    snapshot_files(source)
    shutil.copytree(
        filesystem_path(source),
        filesystem_path(destination),
        ignore=shutil.ignore_patterns(".git") if exclude_git else None,
    )


def validate_inventory(actual: dict[str, dict[str, Any]], expected_git_blobs: dict[str, str]) -> None:
    if set(actual) != set(expected_git_blobs):
        missing = sorted(set(expected_git_blobs) - set(actual))
        extra = sorted(set(actual) - set(expected_git_blobs))
        raise ValueError(f"Snapshot path inventory mismatch: missing={missing[:5]}, extra={extra[:5]}")
    mismatches = [path for path in actual if actual[path]["git_blob"] != expected_git_blobs[path]]
    if mismatches:
        raise ValueError(f"Snapshot differs from pinned Git/patch contents: {mismatches[:5]}")
