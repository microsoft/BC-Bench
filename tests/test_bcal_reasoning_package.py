import hashlib
import importlib
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
package = importlib.import_module("bcal_reasoning_package")


@pytest.mark.parametrize("damage", [None, "archive", "payload", "extra", "version", "missing"])
def test_new_package_admission_checks_archive_full_payload_and_actual_source(tmp_path, monkeypatch, damage):
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "bcal.exe").write_bytes(b"fixture")
    archive = tmp_path / "package.nupkg"
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("tools/net10.0/any/bcal.exe", b"fixture")
    pin = package.PackagePin(
        version="30.0.46.99999-beta", source="c" * 40, archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), runtime_files=1, sdk_package="1.0.29", sdk_runtime="1.0.107"
    )
    monkeypatch.setattr(package.subprocess, "check_output", lambda *a, **k: pin.product_version if damage != "version" else "wrong-source")
    if damage == "archive":
        archive.write_bytes(b"wrong")
    elif damage == "payload":
        (payload / "bcal.exe").write_bytes(b"wrong")
    elif damage == "extra":
        (payload / "extra.dll").write_bytes(b"wrong")
    elif damage == "missing":
        (payload / "bcal.exe").unlink()
    if damage:
        with pytest.raises((package.AdmissionError, FileNotFoundError)):
            pin.verify(payload, archive)
    else:
        assert pin.verify(payload, archive) == 1
