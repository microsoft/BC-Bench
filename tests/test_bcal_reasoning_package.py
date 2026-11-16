import hashlib
import importlib
import json
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


@pytest.mark.parametrize("damage", [None, "model", "ownership", "publish", "reference", "artifact", "expected-seal", "bool-type", "sourcebuilt", "medium-model"])
def test_final_owner_seal_requires_complete_package_bound_proofs_and_sanitizes_paths(tmp_path, monkeypatch, damage):
    archive = tmp_path / "package.nupkg"
    archive.write_bytes(b"synthetic-package")
    pin = package.PackagePin(
        version="30.0.46.99999-beta",
        source="cc3f023be09b313cb0568bbaaad6131404152e3c",
        archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        runtime_files=224,
        sdk_package="1.0.29",
        sdk_runtime="1.0.107",
    )
    index = {}

    def assign(path, value):
        *parents, key = path.split(".")
        target = index
        for parent in parents:
            target = target.setdefault(parent, {})
        target[key] = value

    for path, value in package.owner_facts(pin).items():
        assign(path, value)
    assign("package.bytes", archive.stat().st_size)
    roles = {
        "inventory": "package.inventory",
        "reviewProof": "reviewPackageProof.artifact",
        "effortProof": "runtimeEffortProof.artifact",
        "diagnosticsProof": "runtimeDiagnosticsProof.artifact",
        "ownershipProof": "nativeResetOwnershipProof.artifact",
        "loopbackReset": "nativeLoopbackProof.reset",
        "loopbackControl": "nativeLoopbackProof.control",
        "nativeMedium": "nativeMediumProof.artifact",
    }

    def reference(path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}

    seal = {"schemaVersion": "1.0", "sourceCommitSha": pin.source, "buildId": 3073789, "packageSha256": pin.archive_sha256}
    for role, path in roles.items():
        artifact = tmp_path / f"{role}.json"
        data = {"status": "synthetic"}
        if role in ("loopbackReset", "loopbackControl"):
            data = {
                "identity": {
                    "kind": "source-built-nonpackage" if damage == "sourcebuilt" else "exact-governed-package",
                    "version": pin.version,
                    "source": pin.source,
                    "archiveSha256": pin.archive_sha256,
                    "verifiedRuntimeFiles": pin.runtime_files,
                },
                "forcedTool": "start_new_work" if role == "loopbackReset" else "list_files",
                "providerAttempts": 0,
                "offlineRequests": 2,
                "secondRequestContainsToolResult": True,
                "packagePayloadUnchanged": True,
                "auxiliaryInvocations": 0,
                "terminalEvidence": {"failureMessageSignature": "unknown"},
            }
        elif role == "nativeMedium":
            data = {"status": "verified", "package": pin.model_dump(), "providerAttempts": 0, "models": ["wrong"] if damage == "medium-model" else list(package.MODELS)}
        artifact.write_text(json.dumps(data))
        value = reference(artifact)
        assign(path, value)
        if role != "inventory":
            seal[role] = value
    if damage == "model":
        assign("nativeMediumProof.models", ["gpt-56-reasoning-sol", "gpt-56-reasoning-ceres", "gpt-55-chat"])
    elif damage == "ownership":
        assign("nativeResetOwnershipProof.allPassed", False)
    elif damage == "publish":
        assign("package.buildResult", "inProgress")
    elif damage == "bool-type":
        assign("nativeResetOwnershipProof.allPassed", 1)
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(index))
    seal["index"] = reference(index_path)
    if damage == "reference":
        seal["ownershipProof"] = {**seal["ownershipProof"], "sha256": "0" * 64}
    elif damage == "artifact":
        (tmp_path / "ownershipProof.json").write_text('{"status":"altered"}')
    seal_path = tmp_path / "seal.json"
    seal_path.write_text(json.dumps(seal))
    seal_sha = "0" * 64 if damage == "expected-seal" else reference(seal_path)["sha256"]
    if damage:
        with pytest.raises(package.AdmissionError):
            package.verify_owner_seal(index_path, seal_path, pin, reference(index_path)["sha256"], seal_sha, archive)
    else:
        value = package.verify_owner_seal(index_path, seal_path, pin, reference(index_path)["sha256"], seal_sha, archive)
        assert value["status"] == "verified-offline-package-proofs"
        assert set(value["proofs"]) == set(roles)
        assert str(tmp_path) not in json.dumps(value)
        receipt = tmp_path / "sanitized-owner-admission.json"
        receipt.write_text(json.dumps(value))
        monkeypatch.setattr(package, "OWNER_ADMISSION", receipt)
        assert package.owner_admission(pin) == value
        value["facts"]["nativeResetOwnershipProof.allPassed"] = 1
        receipt.write_text(json.dumps(value))
        with pytest.raises(package.AdmissionError):
            package.owner_admission(pin)
