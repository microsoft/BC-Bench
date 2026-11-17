import hashlib
import json
import sys
import zipfile
from argparse import Namespace
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bcal_package_diagnostic as diagnostic


def package(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    files = {"bcal.exe": b"exe", "bcal.dll": b"cli", "sdk.dll": b"sdk", "native.exe": b"launcher", "native-runtime.dll": b"library"}
    for name, data in files.items():
        (runtime / name).write_bytes(data)
    entries = {diagnostic.PREFIX + name: data for name, data in files.items()}
    entries["Microsoft.BusinessCentral.BCal.CLI.nuspec"] = (
        b'<package xmlns="http://schemas.microsoft.com/packaging/2013/05/nuspec.xsd"><metadata><id>Microsoft.BusinessCentral.BCal.CLI</id><version>30.0.46.99999-beta</version></metadata></package>'
    )
    archive = tmp_path / "package.nupkg"
    with zipfile.ZipFile(archive, "w") as output:
        for name, data in entries.items():
            output.writestr(name, data)

    def inventory(values):
        return tuple(diagnostic.DiagnosticFile(path=name, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data)) for name, data in values.items())

    identity = diagnostic.DiagnosticPackageIdentity(
        package_id="Microsoft.BusinessCentral.BCal.CLI",
        feed="DynamicsSMBTest",
        version="30.0.46.99999-beta",
        source_commit="d" * 40,
        build_id=123,
        product_version="30.0.46.99999+" + "d" * 40,
        sdk_version="1.0.29",
        native_version="1.0.107",
        sdk_path="sdk.dll",
        native_path=("native.exe",),
        native_library_path="native-runtime.dll",
        archive_sha256=diagnostic.sha(archive),
        archive_bytes=archive.stat().st_size,
        owner_inventory_sha256="a" * 64,
        archive_files=inventory(entries),
        files=inventory(files),
    )
    return identity, archive, runtime


@pytest.mark.parametrize("damage", ["none", "archive", "size", "entry", "extra", "case-collision", "traversal", "runtime", "metadata"])
def test_diagnostic_package_binds_archive_complete_inventory_and_metadata(tmp_path, monkeypatch, damage):
    identity, archive, runtime = package(tmp_path)
    monkeypatch.setattr("bcal_nonpackage_diagnostic.subprocess.check_output", lambda *args, **kwargs: identity.product_version)
    if damage == "archive":
        archive.write_bytes(b"changed")
    elif damage == "size":
        identity = identity.model_copy(update={"archive_bytes": 1})
    elif damage == "entry":
        identity = identity.model_copy(update={"archive_files": (identity.archive_files[0].model_copy(update={"sha256": "a" * 64}), *identity.archive_files[1:])})
    elif damage in ("extra", "case-collision", "traversal"):
        path = {"extra": "extra", "case-collision": identity.archive_files[0].path.upper(), "traversal": "../outside"}[damage]
        identity = identity.model_copy(update={"archive_files": (*identity.archive_files, identity.archive_files[0].model_copy(update={"path": path}))})
    elif damage == "runtime":
        identity = identity.model_copy(update={"files": identity.files[:-1]})
    elif damage == "metadata":
        identity = identity.model_copy(update={"version": "30.0.46.88888-beta"})
    if damage == "none":
        proof = identity.verify_archive(archive)
        assert proof["kind"] == "exact-diagnostic-package"
        assert proof["verifiedArchiveFiles"] == 6
        assert proof["governedPackageAdmissionClaimed"] is proof["goldAdmissionClaimed"] is False
        assert identity.verify(runtime)["archiveSha256"] == identity.archive_sha256
    else:
        with pytest.raises(diagnostic.AdmissionError):
            identity.verify_archive(archive)


@pytest.mark.parametrize("damage", ["source", "historical", "kind", "feed", "dirty-patch"])
def test_diagnostic_identity_cannot_claim_old_package_or_sourcebuilt_runtime(tmp_path, damage):
    identity, _, _ = package(tmp_path)
    values = identity.model_dump()
    if damage == "source":
        values["source_commit"] = "e" * 40
    elif damage == "historical":
        values["version"] = "30.0.46.59225-beta"
        values["product_version"] = "30.0.46.59225+" + values["source_commit"]
    elif damage == "kind":
        values["kind"] = "source-built-nonpackage"
    elif damage == "feed":
        values["feed"] = "official"
    else:
        values["patch_sha256"] = "a" * 64
    with pytest.raises(ValidationError):
        diagnostic.DiagnosticPackageIdentity.model_validate(values)


def test_new_package_driver_requires_external_identity_and_rechecks_archive(tmp_path, monkeypatch):
    identity, archive, runtime = package(tmp_path)
    manifest = tmp_path / "identity.json"
    manifest.write_text(identity.model_dump_json())
    args = Namespace(identity=manifest, identity_sha256=diagnostic.sha(manifest), archive=archive, runtime=runtime, output=tmp_path / "safe" / "execution")
    calls = []

    def run_startup(values, *, admitted_identity, observe_stage):
        assert values is args
        assert admitted_identity == identity
        observe_stage("cli_process")
        calls.append(admitted_identity.kind)
        archive.write_bytes(b"changed-during-run")

    monkeypatch.setattr(diagnostic, "run_startup", run_startup)
    with pytest.raises(diagnostic.AdmissionError):
        diagnostic.run(args)
    assert calls == ["exact-diagnostic-package"]
    receipt = json.loads((args.output.parent / "diagnostic-package-admission.json").read_bytes())
    assert receipt["archiveSha256"] == identity.archive_sha256
    assert not receipt["governedPackageAdmissionClaimed"]
    manifest.write_text(manifest.read_text() + " ")
    with pytest.raises(diagnostic.AdmissionError):
        diagnostic.load_identity(manifest, args.identity_sha256)


def test_driver_journal_preserves_failure_before_finally_without_raw_details(tmp_path):
    journal = diagnostic.DiagnosticJournal(tmp_path / "stage.json")
    journal.stage("cli_process")
    try:
        try:
            raise TypeError("PRIVATE_PATH PRIVATE_MESSAGE")
        finally:
            journal.stage("runtime_cleanup")
    except TypeError as error:
        journal.capture(error)
    safe = json.loads(journal.path.read_bytes())
    assert safe == {"status": "failed", "stage": "runtime_cleanup", "failureStage": "cli_process", "exceptionCategory": "type"}
    assert "PRIVATE" not in journal.path.read_text()


@pytest.mark.parametrize("damage", ["none", "hash", "source", "build", "parity", "runtime-count"])
def test_owner_inventory_conversion_requires_exact_external_publication_facts(tmp_path, damage):
    identity, _, _ = package(tmp_path)
    owner = {
        "buildId": identity.build_id,
        "buildResult": "completed/succeeded",
        "sourceCommitSha": identity.source_commit,
        "packageId": identity.package_id,
        "packageVersion": identity.version,
        "feed": identity.feed,
        "productVersion": identity.product_version,
        "packageSha256": identity.archive_sha256,
        "packageBytes": identity.archive_bytes,
        "fileCount": len(identity.archive_files),
        "net10RuntimeFileCount": len(identity.files),
        "archiveStageParity": True,
        "sdkNativeParity59225": True,
        "sdkPackageVersion": identity.sdk_version,
        "nativeVersion": identity.native_version,
        "files": [row.model_dump() for row in identity.archive_files],
        "packagePath": "PRIVATE",
        "stagePath": "PRIVATE",
    }
    if damage == "source":
        owner["sourceCommitSha"] = "e" * 40
    elif damage == "build":
        owner["buildId"] += 1
    elif damage == "parity":
        owner["archiveStageParity"] = False
    elif damage == "runtime-count":
        owner["net10RuntimeFileCount"] += 1
    inventory = tmp_path / "owner.json"
    inventory.write_text(json.dumps(owner))
    digest = diagnostic.sha(inventory)
    if damage == "hash":
        inventory.write_text(inventory.read_text() + " ")
    output = tmp_path / "diagnostic.json"
    if damage == "none":
        prepared = diagnostic.prepare_identity(inventory, digest, identity.source_commit, identity.build_id, output)
        assert prepared.archive_sha256 == identity.archive_sha256
        assert "PRIVATE" not in output.read_text()
        assert b"\r" not in output.read_bytes()
        assert output.read_bytes().endswith(b"\n")
        assert diagnostic.load_identity(output, diagnostic.sha(output)) == prepared
    else:
        with pytest.raises(diagnostic.AdmissionError):
            diagnostic.prepare_identity(inventory, digest, identity.source_commit, identity.build_id, output)
        assert not output.exists()
