"""Verify an immutable private diagnostic archive before extracting any bytes."""

from __future__ import annotations

import argparse
import hashlib
import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from bcal_nonpackage_diagnostic import NonpackageIdentity, sha
from bcal_reasoning_coding import AdmissionError, write_json


def extract(args: argparse.Namespace) -> None:
    if args.archive.stat().st_size != args.archive_bytes or sha(args.archive) != args.archive_sha256:
        raise AdmissionError("Private diagnostic archive hash or size differs.")
    with zipfile.ZipFile(args.archive) as archive:
        records = archive.infolist()
        names = [row.filename for row in records]
        if len({name.casefold() for name in names}) != len(names) or any(row.is_dir() or stat.S_ISLNK(row.external_attr >> 16) for row in records):
            raise AdmissionError("Diagnostic archive has duplicate, directory or symbolic-link entries.")
        for name in names:
            relative = PurePosixPath(name)
            windows = PureWindowsPath(name)
            if relative.is_absolute() or windows.anchor or windows.drive or "\\" in name or any(part in ("..", ".") or ":" in part or part.endswith((" ", ".")) for part in relative.parts):
                raise AdmissionError("Diagnostic archive has an unsafe path.")
        roots = {"identity.json": args.identity_sha256, "source.patch": args.patch_sha256, "local-safe-summary.json": args.summary_sha256}
        for name, digest in roots.items():
            if name not in names or hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise AdmissionError("Diagnostic archive provenance differs.")
        identity = NonpackageIdentity.model_validate_json(archive.read("identity.json"))
        if identity.patch_sha256 != args.patch_sha256:
            raise AdmissionError("Diagnostic dirty-patch identity differs.")
        expected = {*roots, *(f"runtime/{PureWindowsPath(row.path).as_posix()}" for row in identity.files)}
        if set(names) != expected:
            raise AdmissionError("Diagnostic archive inventory has missing or extra entries.")
        for row in identity.files:
            data = archive.read(f"runtime/{PureWindowsPath(row.path).as_posix()}")
            if len(data) != row.bytes or hashlib.sha256(data).hexdigest() != row.sha256:
                raise AdmissionError("Diagnostic archived runtime bytes differ.")
        args.destination.mkdir(parents=True, exist_ok=False)
        for name in names:
            target = args.destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as file:
                file.write(archive.read(name))
    write_json(
        args.receipt,
        {
            "status": "private-nonpackage-archive-verified",
            "archiveSha256": args.archive_sha256,
            "archiveBytes": args.archive_bytes,
            "identitySha256": args.identity_sha256,
            "patchSha256": args.patch_sha256,
            "localSummarySha256": args.summary_sha256,
            "entries": len(names),
            "runtimeFiles": len(identity.files),
            "sourceCommit": identity.source_commit,
            "kind": identity.kind,
            "packageAdmissionClaimed": False,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "destination", "receipt"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("archive-sha256", "identity-sha256", "patch-sha256", "summary-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--archive-bytes", type=int, required=True)
    args = parser.parse_args()
    try:
        extract(args)
    except Exception:  # noqa: BLE001 - private artifact failures must not expose paths or archive contents
        write_json(args.receipt, {"status": "private-nonpackage-archive-rejected", "rawMessageRetained": False})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
