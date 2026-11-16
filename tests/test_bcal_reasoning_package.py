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


@pytest.mark.parametrize("damage", [None, "cache", "duplicate-runtime"])
def test_new_package_discovery_does_not_reuse_historical_archive_identity(tmp_path, monkeypatch, damage):
    installed = tmp_path / "installed"
    payload = installed / "tools" / "net10.0" / "any"
    payload.mkdir(parents=True)
    cache = tmp_path / "cache"
    cache.mkdir()
    for name in ("bcal.exe", "bcal.dll"):
        (payload / name).write_bytes(b"fixture")
    archive = installed / "microsoft.businesscentral.bcal.cli.30.0.46.99999-beta.nupkg"
    with zipfile.ZipFile(archive, "w") as file:
        for name in ("bcal.exe", "bcal.dll"):
            file.writestr("tools/net10.0/any/" + name, b"fixture")
    (cache / "microsoft.businesscentral.bcal.cli.30.0.46.49019-beta.nupkg").write_bytes(b"historical-not-selected")
    pin = package.PackagePin(
        version="30.0.46.99999-beta", source="c" * 40, archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), runtime_files=2, sdk_package="1.0.29", sdk_runtime="1.0.107"
    )
    monkeypatch.setattr(package.subprocess, "check_output", lambda *a, **k: pin.product_version)
    if damage == "cache":
        (cache / archive.name).write_bytes(b"wrong")
    elif damage == "duplicate-runtime":
        other = installed / "other" / "net10.0" / "any"
        other.mkdir(parents=True)
        (other / "bcal.dll").write_bytes(b"fixture")
    if damage:
        with pytest.raises(package.AdmissionError):
            pin.discover(installed, cache)
    else:
        assert pin.discover(installed, cache) == (payload, archive)
