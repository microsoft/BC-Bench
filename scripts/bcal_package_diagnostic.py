"""Separate exact-package admission for a zero-provider startup diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from bcal_nonpackage_diagnostic import DiagnosticFile, RuntimeIdentity, sha
from bcal_nonpackage_diagnostic import run as run_startup
from bcal_reasoning_coding import AdmissionError, write_json
from pydantic import Field, ValidationError, model_validator

PREFIX = "tools/net10.0/any/"
DRIVER_STAGES = frozenset(
    (
        "package_identity",
        "package_archive",
        "network_admission",
        "runtime_identity",
        "symbol_identity",
        "worker_copy",
        "worker_identity",
        "workspace_scaffold",
        "listener_start",
        "coding_command",
        "cli_process",
        "runtime_cleanup",
        "runtime_identity_after",
        "transcript_decode",
        "execution_policy",
        "summary_write",
        "package_archive_after",
    )
)
DRIVER_CATEGORIES = frozenset(("admission", "validation", "json", "io", "process_exit", "process_timeout", "missing_field", "argument", "type", "name", "unknown"))


class DiagnosticJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.body: dict = {"status": "running", "stage": "package_identity"}
        with path.open("x", encoding="utf-8") as stream:
            json.dump(self.body, stream)

    def capture(self, error: BaseException) -> None:
        if "failureStage" not in self.body:
            category = next(
                (
                    name
                    for kind, name in (
                        (AdmissionError, "admission"),
                        (ValidationError, "validation"),
                        (json.JSONDecodeError, "json"),
                        (OSError, "io"),
                        (subprocess.CalledProcessError, "process_exit"),
                        (subprocess.TimeoutExpired, "process_timeout"),
                        (KeyError, "missing_field"),
                        (TypeError, "type"),
                        (NameError, "name"),
                        (ValueError, "argument"),
                    )
                    if isinstance(error, kind)
                ),
                "unknown",
            )
            self.body.update(status="failed", failureStage=self.body["stage"], exceptionCategory=category)
            write_json(self.path, self.body)

    def stage(self, value: str) -> None:
        if value not in DRIVER_STAGES:
            raise AdmissionError("Unknown diagnostic driver stage.")
        if (error := sys.exception()) is not None:
            self.capture(error)
        self.body["stage"] = value
        write_json(self.path, self.body)

    def complete(self) -> None:
        self.body["status"] = "completed"
        write_json(self.path, self.body)


class DiagnosticPackageIdentity(RuntimeIdentity):
    kind: Literal["exact-diagnostic-package"] = "exact-diagnostic-package"
    package_id: Literal["Microsoft.BusinessCentral.BCal.CLI"]
    feed: Literal["DynamicsSMBTest"]
    version: str = Field(pattern=r"^\d+\.\d+\.\d+\.\d+-beta$")
    build_id: int = Field(strict=True, gt=0)
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    archive_bytes: int = Field(strict=True, gt=0)
    owner_inventory_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    archive_files: tuple[DiagnosticFile, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_product_version(self) -> DiagnosticPackageIdentity:
        if self.product_version != self.version.removesuffix("-beta") + "+" + self.source_commit:
            raise ValueError("Diagnostic package product version must bind exact version and source.")
        if self.version == "30.0.46.59225-beta":
            raise ValueError("Historical governed package is not the new diagnostic package.")
        return self

    def provenance(self) -> dict:
        return {
            **super().provenance(),
            "packageId": self.package_id,
            "feed": self.feed,
            "packageVersion": self.version,
            "buildId": self.build_id,
            "archiveSha256": self.archive_sha256,
            "archiveBytes": self.archive_bytes,
            "ownerInventorySha256": self.owner_inventory_sha256,
            "governedPackageAdmissionClaimed": False,
            "goldAdmissionClaimed": False,
        }

    def verify_archive(self, archive: Path) -> dict:
        if archive.stat().st_size != self.archive_bytes or sha(archive) != self.archive_sha256:
            raise AdmissionError("Diagnostic NuGet archive hash or size differs.")
        expected = {}
        for item in self.archive_files:
            path = PurePosixPath(item.path)
            windows = PureWindowsPath(item.path)
            if (
                not item.path
                or path.as_posix() != item.path
                or windows.anchor
                or windows.drive
                or "\\" in item.path
                or any(part in ("..", ".") or ":" in part or part.endswith((" ", ".")) for part in path.parts)
                or item.path.casefold() in expected
            ):
                raise AdmissionError("Diagnostic NuGet inventory path is invalid or duplicated.")
            expected[item.path.casefold()] = item
        runtime = {PREFIX + PureWindowsPath(item.path).as_posix(): item for item in self.files}
        packaged = {item.path: item for item in self.archive_files if item.path.startswith(PREFIX)}
        if len(runtime) != len(self.files) or set(runtime) != set(packaged) or any((row.sha256, row.bytes) != (packaged[name].sha256, packaged[name].bytes) for name, row in runtime.items()):
            raise AdmissionError("Diagnostic archive and runtime inventories differ.")
        with zipfile.ZipFile(archive) as source:
            records = source.infolist()
            names = [row.filename for row in records]
            if (
                len(names) != len(expected)
                or len({name.casefold() for name in names}) != len(names)
                or set(names) != {item.path for item in expected.values()}
                or any(row.is_dir() or stat.S_ISLNK(row.external_attr >> 16) for row in records)
            ):
                raise AdmissionError("Diagnostic NuGet entries differ from the complete inventory.")
            for record in records:
                item = expected[record.filename.casefold()]
                with source.open(record) as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if record.file_size != item.bytes or digest != item.sha256:
                    raise AdmissionError("Diagnostic NuGet entry bytes differ.")
            nuspec = self.package_id + ".nuspec"
            if nuspec not in names:
                raise AdmissionError("Diagnostic NuGet metadata is missing.")
            metadata = ET.fromstring(source.read(nuspec)).find("{*}metadata")
            if metadata is None or metadata.findtext("{*}id") != self.package_id or metadata.findtext("{*}version") != self.version:
                raise AdmissionError("Diagnostic NuGet package ID or version differs.")
        return {**self.provenance(), "verifiedArchiveFiles": len(expected), "verifiedRuntimeFiles": len(self.files)}


def load_identity(path: Path, expected_sha256: str) -> DiagnosticPackageIdentity:
    if sha(path) != expected_sha256:
        raise AdmissionError("Diagnostic package identity hash differs.")
    return DiagnosticPackageIdentity.model_validate_json(path.read_bytes())


def prepare_identity(owner_inventory: Path, expected_sha256: str, source: str, build_id: int, destination: Path) -> DiagnosticPackageIdentity:
    if sha(owner_inventory) != expected_sha256:
        raise AdmissionError("Owner diagnostic package inventory hash differs.")
    owner = json.loads(owner_inventory.read_bytes())
    if (
        owner.get("sourceCommitSha") != source
        or type(owner.get("buildId")) is not int
        or owner["buildId"] != build_id
        or owner.get("buildResult") not in ("succeeded", "completed/succeeded")
        or owner.get("archiveStageParity") is not True
        or owner.get("sdkNativeParity59225") is not True
    ):
        raise AdmissionError("Owner diagnostic package publication facts differ.")
    entries = tuple(DiagnosticFile.model_validate(row) for row in owner["files"])
    runtime = tuple(row.model_copy(update={"path": row.path.removeprefix(PREFIX)}) for row in entries if row.path.startswith(PREFIX))
    if owner.get("fileCount") != len(entries) or owner.get("net10RuntimeFileCount") != len(runtime):
        raise AdmissionError("Owner diagnostic package file counts differ.")
    identity = DiagnosticPackageIdentity(
        package_id=owner["packageId"],
        feed=owner["feed"],
        version=owner["packageVersion"],
        source_commit=source,
        build_id=build_id,
        product_version=owner["productVersion"],
        sdk_version=owner["sdkPackageVersion"],
        native_version=owner["nativeVersion"],
        sdk_path="GitHub.Copilot.SDK.dll",
        native_path=("runtimes/win-x64/native/copilot.exe",),
        archive_sha256=owner["packageSha256"],
        archive_bytes=owner["packageBytes"],
        owner_inventory_sha256=expected_sha256,
        archive_files=entries,
        files=runtime,
    )
    if destination.exists():
        raise AdmissionError("Diagnostic identity preparation cannot overwrite prior evidence.")
    destination.write_text(identity.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    return identity


def run(args: argparse.Namespace) -> None:
    admission = args.output.parent / "diagnostic-package-admission.json"
    if args.output.exists() or admission.exists():
        raise AdmissionError("Diagnostic package execution cannot reuse prior evidence.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    journal = DiagnosticJournal(args.output.parent / "diagnostic-driver-stage.json")
    try:
        identity = load_identity(args.identity, args.identity_sha256)
        journal.stage("package_archive")
        proof = identity.verify_archive(args.archive)
        write_json(admission, {"status": "exact-diagnostic-package-verified", "identitySha256": args.identity_sha256, **proof})
        try:
            run_startup(args, admitted_identity=identity, observe_stage=journal.stage)
        finally:
            journal.stage("package_archive_after")
            identity.verify_archive(args.archive)
        journal.complete()
    except Exception as error:
        journal.capture(error)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runtime", "archive", "identity", "symbols", "work", "output", "network-proof"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--identity-sha256", required=True)
    args = parser.parse_args()
    try:
        run(args)
    except Exception:  # noqa: BLE001 - private native startup details must not reach runner logs
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output.parent / "package-diagnostic-failure.json", {"status": "diagnostic-stopped", "rawMessageRetained": False})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
