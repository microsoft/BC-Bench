"""Strict snapshot metadata and Windows-compatible filesystem operations."""

import hashlib
import json
import os
import shutil
import stat
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


def filesystem_path(path: Path) -> Path:
    absolute = os.path.abspath(path)  # noqa: PTH100 - normalize lexically before any potentially failing Windows filesystem resolution
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return Path(absolute)
    return Path("\\\\?\\UNC\\" + absolute[2:] if absolute.startswith("\\\\") else "\\\\?\\" + absolute)


def snapshot_files(root: Path, *, deadline: float | None = None, observe: Callable[[str, os.stat_result], None] | None = None) -> list[tuple[str, Path]]:
    base = filesystem_path(root)
    root_stat = base.lstat()
    if not stat.S_ISDIR(root_stat.st_mode) or getattr(root_stat, "st_file_attributes", 0) & 0x400:
        raise ValueError("Snapshot root must be a real directory, not a reparse point")
    files = []
    pending = [(base, "")]
    while pending:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("Snapshot enumeration deadline exceeded")
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
                    if observe is not None:
                        observe(relative, info)
                    files.append((relative, Path(entry.path)))
                else:
                    raise ValueError(f"Unsupported snapshot entry: {relative}")
    return sorted(files)


def metadata_scan(root: Path, progress: Path, stage: str) -> dict[str, tuple[int, int]]:
    started, last_report = time.monotonic(), 0.0
    result: dict[str, tuple[int, int]] = {}
    total_bytes = 0

    def observe(relative: str, info: os.stat_result) -> None:
        nonlocal last_report, total_bytes
        now = time.monotonic()
        if now - started > 120:
            raise TimeoutError(f"{stage}: metadata scan exceeded 120 seconds")
        result[relative] = (info.st_size, info.st_mtime_ns)
        total_bytes += info.st_size
        if now - last_report >= 5:
            report_progress(progress, stage, len(result), total_bytes, now - started)
            last_report = now

    snapshot_files(root, deadline=started + 120, observe=observe)
    report_progress(progress, stage, len(result), total_bytes, time.monotonic() - started)
    return result


def report_progress(path: Path, stage: str, files: int, size: int, elapsed: float) -> None:
    row = {"stage": stage, "files": files, "bytes": size, "elapsed_seconds": elapsed}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)


def copy_verified(source: Path, destination: Path, expected: dict[str, dict[str, Any]], progress: Path) -> None:
    report_progress(progress, "planned-context-copy-600s-limit", len(expected), sum(item["bytes"] for item in expected.values()), 0)
    metadata = metadata_scan(source, progress, "copy-source-metadata")
    if {name: item[0] for name, item in metadata.items()} != {name: item["bytes"] for name, item in expected.items()}:
        raise ValueError("Frozen copy source path/size inventory changed")
    started, last_report = time.monotonic(), 0.0
    total_bytes = 0
    filesystem_path(destination).mkdir(parents=True, exist_ok=False)
    for number, (relative, record) in enumerate(expected.items(), 1):
        target = filesystem_path(destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with filesystem_path(source / relative).open("rb") as reader, target.open("xb") as writer:
            while chunk := reader.read(1024 * 1024):
                if time.monotonic() - started > 600:
                    raise TimeoutError("Verified context copy exceeded 600 seconds; partial copy retained")
                digest.update(chunk)
                writer.write(chunk)
                total_bytes += len(chunk)
        if digest.hexdigest() != record["sha256"]:
            raise ValueError(f"Source content differs from checkpoint during copy: {relative}")
        with target.open("rb") as reader:
            copied_digest = hashlib.file_digest(reader, "sha256").hexdigest()
        if copied_digest != record["sha256"]:
            raise ValueError(f"Copied content differs from checkpoint: {relative}")
        now = time.monotonic()
        if now - started > 600:
            raise TimeoutError("Verified context copy exceeded 600 seconds; partial copy retained")
        if now - last_report >= 5:
            report_progress(progress, "verified-context-copy", number, total_bytes, now - started)
            last_report = now
    report_progress(progress, "verified-context-copy-completed", len(expected), total_bytes, time.monotonic() - started)


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
