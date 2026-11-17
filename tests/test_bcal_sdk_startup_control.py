import json
import shutil
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bcal_sdk_startup_control as control


def receipt(failed=False):
    value = {
        "schemaVersion": 1,
        "evidenceSource": "public_sdk_create_session_control",
        "control": "valid-bare-startup",
        "modelSendCalled": False,
        "providerCredentialsFetched": False,
        "requestHandlerAdmissions": 0,
        "operation": "session.create",
        "sessionCreated": not failed,
        "clientDisposed": True,
        "ownedStateRemoved": True,
        "workingDirectoryExists": True,
        "workingDirectoryIsFile": False,
        "exactPackagedSdkAndNativeVerified": True,
        "ownedStateParentWritable": True,
        "tempDirectoryExists": True,
        "tempDirectoryIsFile": False,
        "nativeStartElapsedMilliseconds": 10,
        "sessionCreateElapsedMilliseconds": 20,
        "exitCode": int(failed),
        **control.BINARY_HASHES,
    }
    if failed:
        value["failure"] = {"exceptionCategory": "io", "innerExceptionCategory": "sdk_rpc", "rpcErrorCode": -32603, "rpcErrorDataKind": "absent"}
    return value


@pytest.mark.parametrize("failed", [False, True])
def test_control_exports_only_typed_lifecycle_and_rpc_data_kind(failed):
    body = receipt(failed)
    assert control.safe_control(body) == body
    assert body["sessionCreated"] is not failed
    assert body["modelSendCalled"] is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("message", "PRIVATE"),
        ("errorData", {"PRIVATE": "PRIVATE"}),
        ("path", "PRIVATE"),
        ("control", "invalid-working-directory"),
        ("modelSendCalled", True),
        ("providerCredentialsFetched", True),
        ("requestHandlerAdmissions", 1),
        ("requestHandlerAdmissions", True),
        ("sessionCreated", "true"),
        ("operation", "PRIVATE"),
        ("nativeStartElapsedMilliseconds", -1),
        ("nativeStartElapsedMilliseconds", True),
        ("sdkSha256", "0" * 64),
        ("exactPackagedSdkAndNativeVerified", False),
        ("failure", {"exceptionCategory": "sdk_rpc", "message": "PRIVATE"}),
        ("failure", {"exceptionCategory": "sdk_rpc", "rpcErrorDataKind": "PRIVATE"}),
        ("failure", {"exceptionCategory": "sdk_rpc", "rpcErrorCode": 2**31}),
        ("failure", {"exceptionCategory": "sdk_rpc", "rpcErrorCode": True}),
        ("failure", {"exceptionCategory": "PRIVATE"}),
    ],
)
def test_control_rejects_private_fields_wrong_host_case_and_inconsistent_success(key, value):
    body = receipt()
    body[key] = value
    with pytest.raises(control.AdmissionError):
        control.safe_control(body)


def setup_run(tmp_path, monkeypatch):
    runtime = tmp_path / "package"
    runtime.mkdir()
    (runtime / "bcal.dll").write_bytes(b"packaged")
    work = tmp_path / "owned"
    shutil.copytree(runtime, work / "runtime")
    (work / "control").mkdir()
    (work / "control" / "SdkStartupControl.dll").write_bytes(b"frozen-helper")
    output = tmp_path / "safe" / "execution"
    output.parent.mkdir()
    identity = SimpleNamespace(
        files=[SimpleNamespace(path="bcal.dll", bytes=8, sha256=control.sha(runtime / "bcal.dll"))],
        archive_sha256="b" * 64,
        verify_archive=lambda _: None,
    )
    args = Namespace(work=work, runtime=runtime, output=output, archive=tmp_path / "unused", identity=tmp_path / "unused-id", identity_sha256="a" * 64, network_proof=tmp_path / "unused-denial")
    build = output.parent / "sdk-control-build.json"
    build.write_text(json.dumps({"identitySha256": args.identity_sha256, "buildFiles": control.inventory(work / "control")}))
    args.control_manifest_sha256 = control.sha(build)
    monkeypatch.setattr(control, "load_identity", lambda *_: identity)
    monkeypatch.setattr(control, "verify_denial", lambda _: {"status": "outbound-denial-active"})
    return args


@pytest.mark.parametrize("failed", [False, True])
def test_driver_invokes_only_three_argument_valid_case_once_and_preserves_native_failure(tmp_path, monkeypatch, failed):
    args = setup_run(tmp_path, monkeypatch)
    calls = []

    def invoke(command, **kwargs):
        assert command == ["dotnet", str(args.work / "control" / "SdkStartupControl.dll"), str(args.work / "runtime"), str(args.work / "sdk-state"), str(args.work / "native-control.json")]
        assert kwargs["cwd"] == args.work / "runtime"
        assert kwargs["timeout"] == 90
        assert not any(key.startswith(("BCAL_", "AZURE_", "OPENAI_")) for key in kwargs["env"])
        calls.append(command)
        body = receipt(failed)
        (args.work / "native-control.json").write_text(json.dumps(body))
        return SimpleNamespace(returncode=body["exitCode"], stdout=json.dumps(body), stderr="PRIVATE")

    monkeypatch.setattr(control.subprocess, "run", invoke)
    control.run(args)
    summary = json.loads((args.output / "sdk-control-summary.json").read_bytes())
    assert summary["invocations"] == 1
    assert summary["hostedArguments"] == 3
    assert summary["control"]["exitCode"] == int(failed)
    assert summary["runtimeInventoryUnchanged"] is summary["compiledOutputUnchanged"] is True
    assert "PRIVATE" not in json.dumps(summary)
    with pytest.raises(control.AdmissionError):
        control.run(args)
    assert len(calls) == 1


@pytest.mark.parametrize("damage", ["helper-before", "runtime-before", "manifest-before", "runtime-after", "timeout"])
def test_control_identity_and_timeout_failures_are_closed_and_never_replaced(tmp_path, monkeypatch, damage):
    args = setup_run(tmp_path, monkeypatch)
    calls = []
    if damage == "helper-before":
        (args.work / "control" / "SdkStartupControl.dll").write_bytes(b"changed")
    elif damage == "runtime-before":
        (args.work / "runtime" / "bcal.dll").write_bytes(b"changed")
    elif damage == "manifest-before":
        (args.output.parent / "sdk-control-build.json").write_text("PRIVATE")

    def invoke(command, **kwargs):
        calls.append(command)
        if damage == "timeout":
            raise subprocess.TimeoutExpired(command, 90, output="PRIVATE")
        (args.work / "native-control.json").write_text(json.dumps(receipt()))
        (args.work / "runtime" / "bcal.dll").write_bytes(b"changed")
        return SimpleNamespace(returncode=0, stdout=json.dumps(receipt()))

    monkeypatch.setattr(control.subprocess, "run", invoke)
    with pytest.raises((control.AdmissionError, subprocess.TimeoutExpired)):
        control.run(args)
    assert len(calls) == int(damage in ("runtime-after", "timeout"))
    journal = json.loads((args.output.parent / "sdk-control-driver.json").read_bytes())
    assert journal["status"] == "failed"
    assert journal["exceptionCategory"] == ("process_timeout" if damage == "timeout" else "admission")
    assert "PRIVATE" not in json.dumps(journal)
    assert not (args.output / "sdk-control-summary.json").exists()


def test_partial_console_preserves_cleanup_without_inventing_request_counts(tmp_path):
    output = tmp_path / "execution"
    cleanup = tmp_path / "cleanup.json"
    cleanup.write_text(
        json.dumps(
            {
                **dict.fromkeys(("denialRulesRemoved", "dnsConfigurationUnchanged", "dnsCacheCleared", "dnsProbeSucceeded", "runtimeProcessCleanupVerified", "controlOwnedStateRemoved"), True),
                "providerCredentialsFetched": False,
                "message": "PRIVATE",
            }
        )
    )
    body = control.console(Namespace(output=output, cleanup=cleanup))
    assert "control" not in body
    assert body["cleanup"]["controlOwnedStateRemoved"] is True
    assert "PRIVATE" not in json.dumps(body)


def test_unexpected_rejected_request_count_is_retained_before_driver_stops(tmp_path, monkeypatch):
    args = setup_run(tmp_path, monkeypatch)
    body = receipt(failed=True)
    body["requestHandlerAdmissions"] = 1

    def invoke(command, **kwargs):
        (args.work / "native-control.json").write_text(json.dumps(body))
        return SimpleNamespace(returncode=1, stdout=json.dumps(body))

    monkeypatch.setattr(control.subprocess, "run", invoke)
    with pytest.raises(control.AdmissionError, match="forbidden request"):
        control.run(args)
    assert json.loads((args.output / "sdk-control-receipt.json").read_bytes())["requestHandlerAdmissions"] == 1
    assert not (args.output / "sdk-control-summary.json").exists()


def test_owner_frozen_source_and_project_bytes_have_not_changed():
    source = Path(__file__).resolve().parents[1] / "experiments" / "bcal-sdk-startup-control"
    for name, (digest, size) in control.SOURCES.items():
        assert (source / name).stat().st_size == size
        assert control.sha(source / name) == digest
