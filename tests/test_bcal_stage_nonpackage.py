import hashlib
import json
import sys
import zipfile
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bcal_stage_nonpackage as stage
from bcal_reasoning_coding import AdmissionError


@pytest.mark.parametrize("damage", ["none", "hash", "bytes", "extra", "traversal", "case-collision", "payload", "patch", "missing"])
def test_private_archive_is_verified_before_any_extraction(tmp_path, damage):
    def digest(value):
        return hashlib.sha256(value).hexdigest()

    files = {"bcal.exe": b"synthetic-exe", "bcal.dll": b"synthetic-cli", "sdk.dll": b"synthetic-sdk", "native.exe": b"synthetic-launcher", "native.dll": b"synthetic-library"}
    patch = b"synthetic-patch"
    manifest = json.dumps(
        {
            "source_commit": "c" * 40,
            "patch_sha256": digest(patch),
            "product_version": "synthetic",
            "sdk_version": "1.0.29",
            "native_version": "1.0.107",
            "sdk_path": "sdk.dll",
            "native_path": ["native.exe"],
            "native_library_path": "native.dll",
            "files": [{"path": name, "bytes": len(data), "sha256": digest(data)} for name, data in files.items()],
        }
    ).encode()
    summary = b'{"providerAttempts":0}'
    entries = {"identity.json": manifest, "source.patch": patch, "local-safe-summary.json": summary, **{f"runtime/{name}": data for name, data in files.items()}}
    if damage in ("extra", "traversal", "case-collision"):
        entries[{"extra": "extra.txt", "traversal": "../outside.txt", "case-collision": "runtime/BCAL.EXE"}[damage]] = b"unexpected"
    elif damage == "payload":
        entries["runtime/bcal.dll"] = b"changed"
    elif damage == "patch":
        entries["source.patch"] = b"changed"
    elif damage == "missing":
        del entries["runtime/sdk.dll"]
    archive = tmp_path / "runtime.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for name, data in entries.items():
            output.writestr(name, data)
    args = Namespace(
        archive=archive,
        archive_sha256="a" * 64 if damage == "hash" else stage.sha(archive),
        archive_bytes=0 if damage == "bytes" else archive.stat().st_size,
        identity_sha256=digest(manifest),
        patch_sha256=digest(patch),
        summary_sha256=digest(summary),
        destination=tmp_path / "extracted",
        receipt=tmp_path / "safe.json",
    )
    if damage == "none":
        stage.extract(args)
        assert (args.destination / "runtime" / "bcal.exe").read_bytes() == files["bcal.exe"]
        proof = json.loads(args.receipt.read_bytes())
        assert proof["entries"] == 8
        assert proof["runtimeFiles"] == 5
        assert not proof["packageAdmissionClaimed"]
    else:
        with pytest.raises(AdmissionError):
            stage.extract(args)
        assert not args.destination.exists()
