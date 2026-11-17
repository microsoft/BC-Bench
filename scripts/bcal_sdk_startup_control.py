"""Source-only, no-Send public SDK control for one exact diagnostic package."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

from bcal_diagnostic_console import cleanup_receipt
from bcal_nonpackage_diagnostic import sha
from bcal_package_diagnostic import DiagnosticPackageIdentity, load_identity
from bcal_reasoning_coding import AdmissionError, process_environment, write_json
from bcal_startup_fixture import verify_denial

SOURCES = {
    "Program.cs": ("587988cdf27f79c0392af8530cfad25703908d75f9e2a1236374f749fccbbf4c", 7376),
    "SdkStartupControl.csproj": ("4e6565af94d426fb3df0b85a0aa8372d10a45ef2f810a988bd469945b14c8cbc", 853),
}
BINARY_HASHES = {
    "sdkSha256": "f788257d2b1d8f158a85ce1940d2f757495e6e9c40406973f9ae16d7d12b7f1f",
    "nativeSha256": "5c817c3f315da691e31a3a2acbd7ab9a8ae4cea0aebb456999ccfa0ed1dade92",
    "launcherSha256": "776e6a9c6365c7c5d60f4e6f692a5e16f9562a7add3347fe591342d62c5c4149",
}
DEPENDENCIES = frozenset(
    ("GitHub.Copilot.SDK.dll", "Microsoft.Extensions.AI.Abstractions.dll", "Microsoft.Extensions.Logging.Abstractions.dll", "Microsoft.Extensions.DependencyInjection.Abstractions.dll")
)
HELPER_FILES = frozenset(("SdkStartupControl.dll", "SdkStartupControl.pdb", "SdkStartupControl.deps.json", "SdkStartupControl.runtimeconfig.json"))
FAILURE_CATEGORIES = frozenset(("sdk_rpc", "canceled", "access_denied", "directory_missing", "file_missing", "io", "invalid_operation", "argument", "unknown"))
ERROR_DATA_KINDS = frozenset(("Object", "Array", "String", "Number", "True", "False", "Null", "Undefined", "absent"))
BOOLEAN_FIELDS = frozenset(
    (
        "modelSendCalled",
        "providerCredentialsFetched",
        "sessionCreated",
        "clientDisposed",
        "ownedStateRemoved",
        "workingDirectoryExists",
        "workingDirectoryIsFile",
        "exactPackagedSdkAndNativeVerified",
        "ownedStateParentWritable",
        "tempDirectoryExists",
        "tempDirectoryIsFile",
    )
)
FAILURE_FIELDS = frozenset(("failure", "cleanupFailure", "stateCleanupFailure", "receiptWriteFailure"))
STAGES = frozenset(("control_admission", "control_identity", "control_invocation", "control_receipt", "control_identity_after", "control_completed"))
DRIVER_CATEGORIES = frozenset(("admission", "process_timeout", "process_exit", "io", "json", "unknown"))


def inventory(root: Path) -> list[dict]:
    files = sorted((path for path in root.rglob("*") if path.is_file()), key=lambda path: path.relative_to(root).as_posix())
    if not files or any(path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root.parent) for path in files):
        raise AdmissionError("Control inventory is empty or linked.")
    return [{"path": path.relative_to(root).as_posix(), "sha256": sha(path), "bytes": path.stat().st_size} for path in files]


def verify_runtime(identity: DiagnosticPackageIdentity, runtime: Path) -> None:
    expected = sorted(({"path": PureWindowsPath(row.path).as_posix(), "sha256": row.sha256, "bytes": row.bytes} for row in identity.files), key=lambda row: row["path"])
    if inventory(runtime) != expected:
        raise AdmissionError("Control runtime differs from the complete package inventory.")


def safe_control(value: object) -> dict:
    if not isinstance(value, dict):
        raise AdmissionError("SDK control receipt must be an object.")
    allowed = (
        {"schemaVersion", "evidenceSource", "control", "requestHandlerAdmissions", "operation", "nativeStartElapsedMilliseconds", "sessionCreateElapsedMilliseconds", "exitCode"}
        | BOOLEAN_FIELDS
        | FAILURE_FIELDS
        | BINARY_HASHES.keys()
    )
    if (
        set(value) - allowed
        or type(value.get("schemaVersion")) is not int
        or value["schemaVersion"] != 1
        or value.get("evidenceSource") != "public_sdk_create_session_control"
        or value.get("control") != "valid-bare-startup"
    ):
        raise AdmissionError("SDK control schema or hosted case is not admitted.")
    if value.get("operation") not in ("preflight", "native_start", "session.create"):
        raise AdmissionError("SDK control operation is unknown.")
    for key in BOOLEAN_FIELDS & value.keys():
        if type(value[key]) is not bool:
            raise AdmissionError("SDK control boolean is invalid.")
    for key in ("modelSendCalled", "providerCredentialsFetched"):
        if value.get(key) is not False:
            raise AdmissionError("SDK control crossed the no-Send or credential boundary.")
    for key in ("sessionCreated", "clientDisposed", "ownedStateRemoved"):
        if type(value.get(key)) is not bool:
            raise AdmissionError("SDK control lifecycle boolean is missing.")
    if type(value.get("requestHandlerAdmissions")) is not int or not 0 <= value["requestHandlerAdmissions"] < 2**31:
        raise AdmissionError("SDK control request count is invalid.")
    if type(value.get("exitCode")) is not int or value["exitCode"] not in (0, 1):
        raise AdmissionError("SDK control exit code is invalid.")
    for key in ("nativeStartElapsedMilliseconds", "sessionCreateElapsedMilliseconds"):
        if key in value and (type(value[key]) is not int or not 0 <= value[key] < 2**63):
            raise AdmissionError("SDK control timing is invalid.")
    for key, expected in BINARY_HASHES.items():
        if key in value and value[key] != expected:
            raise AdmissionError("SDK control package binary differs.")
    for key in FAILURE_FIELDS & value.keys():
        failure = value[key]
        if not isinstance(failure, dict) or set(failure) - {"exceptionCategory", "innerExceptionCategory", "rpcErrorCode", "rpcErrorDataKind"}:
            raise AdmissionError("SDK control failure shape is not admitted.")
        if failure.get("exceptionCategory") not in FAILURE_CATEGORIES or ("innerExceptionCategory" in failure and failure["innerExceptionCategory"] not in FAILURE_CATEGORIES):
            raise AdmissionError("SDK control failure category is unknown.")
        if "rpcErrorCode" in failure and (type(failure["rpcErrorCode"]) is not int or not -(2**31) <= failure["rpcErrorCode"] < 2**31):
            raise AdmissionError("SDK control RPC code is invalid.")
        if "rpcErrorDataKind" in failure and failure["rpcErrorDataKind"] not in ERROR_DATA_KINDS:
            raise AdmissionError("SDK control RPC data kind is unknown.")
    if value["exitCode"] == 0 and (
        value["requestHandlerAdmissions"] != 0 or any(value[key] is not True for key in ("sessionCreated", "clientDisposed", "ownedStateRemoved")) or FAILURE_FIELDS & value.keys()
    ):
        raise AdmissionError("SDK control success conflicts with lifecycle evidence.")
    if value["exitCode"] == 0 and (
        any(value.get(key) != digest for key, digest in BINARY_HASHES.items())
        or value.get("exactPackagedSdkAndNativeVerified") is not True
        or value.get("workingDirectoryExists") is not True
        or value.get("workingDirectoryIsFile") is not False
    ):
        raise AdmissionError("SDK control success lacks exact package or working-directory evidence.")
    return value


def prepare(args: argparse.Namespace) -> None:
    identity = load_identity(args.identity, args.identity_sha256)
    identity.verify_archive(args.archive)
    verify_runtime(identity, args.runtime)
    if args.work.exists() or args.output.exists() or (args.output.parent / "sdk-control-build.json").exists():
        raise AdmissionError("SDK control preparation cannot reuse prior state.")
    source = Path("experiments") / "bcal-sdk-startup-control"
    for name, (digest, size) in SOURCES.items():
        if (source / name).stat().st_size != size or sha(source / name) != digest:
            raise AdmissionError("Frozen public SDK source bytes differ.")
    args.work.mkdir(parents=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    runtime = args.work / "runtime"
    shutil.copytree(args.runtime, runtime)
    verify_runtime(identity, runtime)
    project = args.work / "source"
    project.mkdir()
    for name in SOURCES:
        shutil.copyfile(source / name, project / name)
    write_json(project / "global.json", {"sdk": {"version": "10.0.100", "rollForward": "latestFeature", "allowPrerelease": False}})
    environment = process_environment()
    environment.update(DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE="true", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1", DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1")
    sdk = subprocess.check_output(["dotnet", "--version"], cwd=project, env=environment, text=True, timeout=30).strip()
    if re.fullmatch(r"10\.0\.[0-9]+", sdk) is None:
        raise AdmissionError("Stable .NET10 SDK is required.")
    for command in (
        ["dotnet", "restore", "SdkStartupControl.csproj", "--source", str(project), "-p:NuGetAudit=false"],
        ["dotnet", "build", "SdkStartupControl.csproj", "--no-restore", "-c", "Release", "-o", str(args.work / "control"), f"-p:BcalRuntimeDirectory={runtime}", "-p:UseAppHost=false"],
    ):
        subprocess.run(command, cwd=project, env=environment, capture_output=True, text=True, timeout=180, check=True)
    built = inventory(args.work / "control")
    expected = {PureWindowsPath(row.path).as_posix(): (row.sha256, row.bytes) for row in identity.files}
    names = {row["path"] for row in built}
    if not DEPENDENCIES.issubset(names) or not HELPER_FILES.issubset(names):
        raise AdmissionError("SDK control output is incomplete.")
    for row in built:
        if row["path"] not in HELPER_FILES and expected.get(row["path"]) != (row["sha256"], row["bytes"]):
            raise AdmissionError("SDK control copied dependency is not exact package content.")
    verify_runtime(identity, runtime)
    write_json(
        args.output.parent / "sdk-control-build.json",
        {
            "status": "offline-built-and-frozen",
            "identitySha256": args.identity_sha256,
            "dotnetSdkVersion": sdk,
            "packageArchiveSha256": identity.archive_sha256,
            "packageRuntimeFiles": len(identity.files),
            "sourceFiles": [{"path": name, "sha256": digest, "bytes": size} for name, (digest, size) in SOURCES.items()],
            "buildFiles": built,
            "hostedArguments": 3,
            "invocationLimit": 1,
            "modelSendAllowed": False,
        },
    )


def run(args: argparse.Namespace) -> None:
    journal_path = args.output.parent / "sdk-control-driver.json"
    if journal_path.exists() or args.output.exists():
        raise AdmissionError("SDK control invocation cannot reuse prior evidence.")
    args.output.mkdir()
    journal = {"status": "running", "stage": "control_admission"}

    def stage(value: str) -> None:
        journal["stage"] = value
        write_json(journal_path, journal)

    def execute() -> None:
        stage("control_admission")
        verify_denial(args.network_proof)
        identity = load_identity(args.identity, args.identity_sha256)
        if sha(args.output.parent / "sdk-control-build.json") != args.control_manifest_sha256:
            raise AdmissionError("Frozen hosted control build identity differs.")
        build = json.loads((args.output.parent / "sdk-control-build.json").read_bytes())
        stage("control_identity")
        identity.verify_archive(args.archive)
        verify_runtime(identity, args.runtime)
        verify_runtime(identity, args.work / "runtime")
        if inventory(args.work / "control") != build["buildFiles"] or build["identitySha256"] != args.identity_sha256:
            raise AdmissionError("SDK control output changed after offline freeze.")
        with (args.output.parent / "sdk-control-execution-once.json").open("x", encoding="utf-8") as file:
            json.dump({"invocations": 1, "hostedArguments": 3, "modelSendAllowed": False}, file)
        stage("control_invocation")
        receipt_path = args.work / "native-control.json"
        result = subprocess.run(
            ["dotnet", str(args.work / "control" / "SdkStartupControl.dll"), str(args.work / "runtime"), str(args.work / "sdk-state"), str(receipt_path)],
            cwd=args.work / "runtime",
            env=process_environment(),
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        stage("control_receipt")
        safe = safe_control(json.loads(receipt_path.read_bytes()))
        if json.loads(result.stdout) != safe or result.returncode != safe["exitCode"]:
            raise AdmissionError("SDK control console and receipt differ.")
        write_json(args.output / "sdk-control-receipt.json", safe)
        if safe["requestHandlerAdmissions"] != 0:
            raise AdmissionError("SDK control attempted forbidden request forwarding.")
        stage("control_identity_after")
        identity.verify_archive(args.archive)
        verify_runtime(identity, args.runtime)
        verify_runtime(identity, args.work / "runtime")
        if inventory(args.work / "control") != build["buildFiles"]:
            raise AdmissionError("SDK control output changed during execution.")
        write_json(
            args.output / "sdk-control-summary.json",
            {
                "status": "native-control-captured",
                "benchSource": os.environ.get("GITHUB_SHA"),
                "packageArchiveSha256": identity.archive_sha256,
                "runtimeInventoryUnchanged": True,
                "compiledOutputUnchanged": True,
                "hostedArguments": 3,
                "invocations": 1,
                "noSendSourceVerified": True,
                "control": safe,
            },
        )
        journal["status"] = "completed"
        stage("control_completed")

    try:
        execute()
    except Exception as error:
        category = next(
            (
                name
                for kind, name in (
                    (AdmissionError, "admission"),
                    (subprocess.TimeoutExpired, "process_timeout"),
                    (subprocess.CalledProcessError, "process_exit"),
                    (OSError, "io"),
                    (json.JSONDecodeError, "json"),
                )
                if isinstance(error, kind)
            ),
            "unknown",
        )
        journal.update(status="failed", exceptionCategory=category)
        write_json(journal_path, journal)
        raise


def console(args: argparse.Namespace) -> dict:
    cleanup = cleanup_receipt(args.cleanup)
    raw_cleanup = json.loads(args.cleanup.read_bytes())
    if type(raw_cleanup.get("controlOwnedStateRemoved")) is not bool:
        raise AdmissionError("SDK control state cleanup evidence is missing.")
    cleanup["controlOwnedStateRemoved"] = raw_cleanup["controlOwnedStateRemoved"]
    path = args.output.parent / "sdk-control-driver.json"
    driver = json.loads(path.read_bytes()) if path.exists() else None
    if driver is not None and (
        set(driver) - {"status", "stage", "exceptionCategory"}
        or driver.get("status") not in ("running", "failed", "completed")
        or driver.get("stage") not in STAGES
        or ("exceptionCategory" in driver and driver["exceptionCategory"] not in DRIVER_CATEGORIES)
    ):
        raise AdmissionError("SDK control driver state is not closed.")
    path = args.output / "sdk-control-receipt.json"
    value = {"evidenceSource": "post_cleanup_public_sdk_control", "cleanup": cleanup, "driver": driver}
    if path.exists():
        value["control"] = safe_control(json.loads(path.read_bytes()))
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "console"))
    for name in ("runtime", "archive", "identity", "work", "network-proof", "cleanup"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--identity-sha256")
    parser.add_argument("--control-manifest-sha256")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            prepare(args)
        elif args.action == "run":
            run(args)
        else:
            value = console(args)
            write_json(args.output.parent / "sdk-control-console.json", value)
            sys.stdout.write("BCAL_SAFE_DIAGNOSTIC " + json.dumps(value, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001 - never emit private runtime messages, source paths or RPC data
        sys.stdout.write('BCAL_SAFE_DIAGNOSTIC {"evidenceSource":"public_sdk_control_driver","status":"closed_failure"}\n')
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
