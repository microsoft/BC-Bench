"""Exact opt-in runtime identity; historical package admission is unchanged."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from functools import reduce
from pathlib import Path

from bcal_reasoning_coding import MODELS, AdmissionError, process_environment
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "experiments" / "bcal-reasoning-gold" / "package.json"
OWNER_ADMISSION = PROFILE.with_name("owner-proof-admission.json")


class PackagePin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(pattern=r"^\d+\.\d+\.\d+\.\d+-beta$")
    source: str = Field(pattern=r"^[a-f0-9]{40}$")
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_files: int = Field(strict=True, gt=0)
    sdk_package: str
    sdk_runtime: str

    def discover(self, installed: Path, cache: Path) -> tuple[Path, Path]:
        binaries = [path for path in installed.rglob("bcal.dll") if path.parent.name == "any" and path.parent.parent.name == "net10.0"]
        name = f"microsoft.businesscentral.bcal.cli.{self.version}.nupkg"
        archives = list(installed.rglob(name))
        if (cache / name).is_file() and cache / name not in archives:
            archives.append(cache / name)
        if len(binaries) != 1 or not archives or any(hashlib.sha256(path.read_bytes()).hexdigest() != self.archive_sha256 for path in archives):
            raise AdmissionError("Exact new package discovery failed.")
        self.verify(binaries[0].parent, archives[0])
        return binaries[0].parent, archives[0]

    @property
    def product_version(self) -> str:
        return self.version.removesuffix("-beta") + "+" + self.source

    def verify(self, package: Path, archive: Path) -> int:
        if hashlib.sha256(archive.read_bytes()).hexdigest() != self.archive_sha256:
            raise AdmissionError("Opt-in package archive hash differs.")
        expected = set()
        with zipfile.ZipFile(archive) as source:
            for item in source.infolist():
                prefix = "tools/net10.0/any/"
                if item.is_dir() or not item.filename.startswith(prefix):
                    continue
                relative = Path(item.filename[len(prefix) :])
                if relative.is_absolute() or ".." in relative.parts or relative in expected:
                    raise AdmissionError("Invalid or duplicate packaged payload path.")
                expected.add(relative)
                if hashlib.sha256(source.read(item)).digest() != hashlib.sha256((package / relative).read_bytes()).digest():
                    raise AdmissionError("Opt-in runtime payload differs from the archive.")
        if len(expected) != self.runtime_files or {path.relative_to(package) for path in package.rglob("*") if path.is_file()} != expected:
            raise AdmissionError("Opt-in runtime inventory has missing or extra files.")
        actual = subprocess.check_output([str(package / "bcal.exe"), "--version"], env=process_environment(), text=True, timeout=30).strip()
        if actual != self.product_version:
            raise AdmissionError("Opt-in executable version/source differs.")
        return len(expected)


def load_pin() -> PackagePin:
    return PackagePin.model_validate_json(PROFILE.read_bytes())


def validate_tool_proof(path: Path, pin: dict, tool: str) -> None:
    proof = json.loads(path.read_bytes())
    identity = proof["identity"]
    if not (
        identity["kind"] == "exact-governed-package"
        and identity["version"] == pin["version"]
        and identity["source"] == pin["source"]
        and identity["archiveSha256"] == pin["archive_sha256"]
        and identity["verifiedRuntimeFiles"] == pin["runtime_files"]
        and proof["forcedTool"] == tool
        and proof["providerAttempts"] == 0
        and proof["offlineRequests"] == 2
        and proof["secondRequestContainsToolResult"] is True
        and proof["packagePayloadUnchanged"] is True
        and proof["auxiliaryInvocations"] == 0
        and proof["terminalEvidence"]["failureMessageSignature"] != "callback_fence_guard"
    ):
        raise AdmissionError("Actual package reset/control proof is not admitted.")


def owner_facts(pin: PackagePin) -> dict:
    return {
        "schemaVersion": "1.0",
        "readiness": "offline-package-proofs-complete",
        "sourceCommitSha": "cc3f023be09b313cb0568bbaaad6131404152e3c",
        "branch": "esben-kristoffersen-bcal-copilot-sdk",
        "resetPatchBaseSha": "9d1dc08c4f9757b6a74dfe9474cfa442bbf2ff3f",
        "resetPatchId": "55e3384e594759bc9a6a0b3fb6092f0d2c4b6ae5",
        "package.id": "Microsoft.BusinessCentral.BCal.CLI",
        "package.version": pin.version,
        "package.feed": "DynamicsSMBTest",
        "package.buildId": 3073789,
        "package.buildResult": "completed/succeeded",
        "package.productVersion": pin.product_version,
        "package.sha256": pin.archive_sha256,
        "package.admittedFramework": "net10.0",
        "package.runtimeFileCount": pin.runtime_files,
        "reviewPackageProof.defaultRuntime": "legacy",
        "reviewPackageProof.promptParity49019": True,
        "runtimeEffortProof.nativeEffortCatalogParity49019": True,
        "runtimeDiagnosticsProof.correlatedFailures": 8,
        "runtimeDiagnosticsProof.successfulCases": 1,
        "nativeResetOwnershipProof.caseCount": 11,
        "nativeResetOwnershipProof.allPassed": True,
        "nativeLoopbackProof.secondRequestContainsToolResultBoth": True,
        "nativeLoopbackProof.packagePayloadUnchangedBoth": True,
        "nativeMediumProof.models": list(MODELS),
        "nativeMediumProof.allThreeExplicitMediumVerified": True,
        "sdk.packageVersion": "1.0.29",
        "sdk.nativeVersion": "1.0.107",
        "sdk.sdkAndNativePayloadParity49019": True,
        "providerRequestsHere": 0,
        "semanticSmokeDispatchedHere": False,
        "duplicateOrReplacementBuildsQueued": 0,
        "newTerminalStates": [],
        "newWholeTerminalSignatures": [],
    }


def verify_owner_seal(index_path: Path, seal_path: Path, pin: PackagePin, index_sha256: str, seal_sha256: str, archive: Path) -> dict:
    def exact(path: Path, digest: str, size: int | None = None) -> bytes:
        if not path.is_absolute():
            raise AdmissionError("Owner proof references must be absolute local artifacts.")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest or (size is not None and (type(size) is not int or len(raw) != size)):
            raise AdmissionError("Owner proof artifact hash or size differs.")
        return raw

    def field(value: dict, path: str) -> object:
        return reduce(lambda parent, key: parent[key], path.split("."), value)

    index = json.loads(exact(index_path, index_sha256))
    seal = json.loads(exact(seal_path, seal_sha256))
    archive_bytes = len(exact(archive, pin.archive_sha256, index["package"]["bytes"]))
    expected = owner_facts(pin)
    if (
        pin.source != expected["sourceCommitSha"]
        or pin.sdk_package != "1.0.29"
        or pin.sdk_runtime != "1.0.107"
        or any(field(index, name) != value or type(field(index, name)) is not type(value) for name, value in expected.items())
    ):
        raise AdmissionError("Final owner index facts do not admit this package.")
    if any(seal[name] != value for name, value in {"schemaVersion": "1.0", "sourceCommitSha": pin.source, "buildId": 3073789, "packageSha256": pin.archive_sha256}.items()):
        raise AdmissionError("Final owner seal identity differs.")
    if seal["index"]["sha256"] != index_sha256 or exact(Path(seal["index"]["path"]), index_sha256, seal["index"]["bytes"]) != index_path.read_bytes():
        raise AdmissionError("Final owner index reference differs.")
    paths = {
        "inventory": "package.inventory",
        "reviewProof": "reviewPackageProof.artifact",
        "effortProof": "runtimeEffortProof.artifact",
        "diagnosticsProof": "runtimeDiagnosticsProof.artifact",
        "ownershipProof": "nativeResetOwnershipProof.artifact",
        "loopbackReset": "nativeLoopbackProof.reset",
        "loopbackControl": "nativeLoopbackProof.control",
        "nativeMedium": "nativeMediumProof.artifact",
    }
    proofs = {}
    for role, path in paths.items():
        reference = field(index, path)
        if role != "inventory" and seal[role] != reference:
            raise AdmissionError("Owner seal and index artifact references differ.")
        raw = exact(Path(reference["path"]), reference["sha256"], reference["bytes"])
        if role in ("loopbackReset", "loopbackControl"):
            validate_tool_proof(Path(reference["path"]), pin.model_dump(), "start_new_work" if role == "loopbackReset" else "list_files")
        elif role == "nativeMedium":
            medium = json.loads(raw)
            if medium["status"] != "verified" or medium["package"] != pin.model_dump() or medium["models"] != list(MODELS) or medium["providerAttempts"] != 0:
                raise AdmissionError("Final owner medium proof belongs to different package/models.")
        proofs[role] = {"sha256": reference["sha256"], "bytes": reference["bytes"]}
    return {
        "status": "verified-offline-package-proofs",
        "package": pin.model_dump(),
        "facts": expected,
        "indexSha256": index_sha256,
        "sealSha256": seal_sha256,
        "packageArchiveBytes": archive_bytes,
        "proofs": proofs,
    }


def owner_admission(pin: PackagePin) -> dict:
    value = json.loads(OWNER_ADMISSION.read_bytes())
    roles = {"inventory", "reviewProof", "effortProof", "diagnosticsProof", "ownershipProof", "loopbackReset", "loopbackControl", "nativeMedium"}
    digests = [value["indexSha256"], value["sealSha256"], *(proof["sha256"] for proof in value["proofs"].values())]
    if (
        value["status"] != "verified-offline-package-proofs"
        or pin.source != "cc3f023be09b313cb0568bbaaad6131404152e3c"
        or pin.sdk_package != "1.0.29"
        or pin.sdk_runtime != "1.0.107"
        or value["package"] != pin.model_dump()
        or json.dumps(value["facts"], sort_keys=True) != json.dumps(owner_facts(pin), sort_keys=True)
        or type(value["packageArchiveBytes"]) is not int
        or value["packageArchiveBytes"] <= 0
        or set(value["proofs"]) != roles
        or any(not re.fullmatch(r"[a-f0-9]{64}", digest) for digest in digests)
        or any(type(proof["bytes"]) is not int or proof["bytes"] <= 0 for proof in value["proofs"].values())
    ):
        raise AdmissionError("Sanitized owner proof admission differs from the frozen package.")
    return value
