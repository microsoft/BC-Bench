import hashlib
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bcal_nonpackage_diagnostic as diagnostic


def identity(tmp_path):
    values = {"bcal.exe": b"synthetic-exe", "bcal.dll": b"synthetic-cli", "sdk.dll": b"synthetic-sdk", "native.exe": b"synthetic-native"}
    for name, content in values.items():
        (tmp_path / name).write_bytes(content)
    return diagnostic.NonpackageIdentity(
        source_commit="c" * 40,
        product_version="diagnostic-test",
        sdk_version="1.0.29",
        native_version="1.0.107",
        sdk_path="sdk.dll",
        native_path="native.exe",
        files=tuple(diagnostic.DiagnosticFile(path=name, sha256=hashlib.sha256(content).hexdigest(), bytes=len(content)) for name, content in values.items()),
    )


@pytest.mark.parametrize("damage", ["none", "changed", "extra", "missing", "version", "case-collision", "traversal", "absolute", "stream", "role"])
def test_nonpackage_identity_is_complete_exact_and_never_governed_package(tmp_path, monkeypatch, damage):
    pin = identity(tmp_path)
    monkeypatch.setattr(diagnostic.subprocess, "check_output", lambda *args, **kwargs: "wrong" if damage == "version" else "diagnostic-test")
    if damage == "changed":
        (tmp_path / "bcal.dll").write_bytes(b"changed")
    elif damage == "extra":
        (tmp_path / "unexpected.dll").write_bytes(b"unexpected")
    elif damage == "missing":
        (tmp_path / "sdk.dll").unlink()
    elif damage in ("case-collision", "traversal", "absolute", "stream"):
        path = {"case-collision": "BCAL.EXE", "traversal": r"..\outside", "absolute": r"C:\outside", "stream": "bcal.exe:secret"}[damage]
        pin = pin.model_copy(update={"files": (*pin.files, pin.files[0].model_copy(update={"path": path}))})
    elif damage == "role":
        pin = pin.model_copy(update={"native_path": "sdk.dll"})
    if damage == "none":
        proof = pin.verify(tmp_path)
        assert proof["kind"] == "source-built-nonpackage"
        assert not proof["packageAdmissionClaimed"]
        assert proof["verifiedFiles"] == 4
        assert "path" not in json.dumps(proof)
    else:
        with pytest.raises((diagnostic.AdmissionError, FileNotFoundError)):
            pin.verify(tmp_path)


def test_manifest_requires_external_hash_and_pins_dirty_patch(tmp_path):
    pin = identity(tmp_path).model_copy(update={"patch_sha256": "a" * 64})
    path = tmp_path / "identity.json"
    path.write_text(pin.model_dump_json())
    digest = diagnostic.sha(path)
    assert diagnostic.load_identity(path, digest).patch_sha256 == "a" * 64
    path.write_text(path.read_text() + " ")
    with pytest.raises(diagnostic.AdmissionError):
        diagnostic.load_identity(path, digest)


@pytest.mark.parametrize("stage", sorted(diagnostic.NATIVE_FAILURE_STAGES))
def test_native_failure_only_exports_closed_stage_and_categories(stage):
    failure = {"stage": stage, "exceptionCategory": "io", "innerExceptionCategory": "access_denied", "httpStatusCode": 400, "message": "PRIVATE", "path": "PRIVATE", "type": "PRIVATE"}
    proof = diagnostic.safe_native_failure(failure)
    assert proof == {"stage": stage, "exceptionCategory": "io", "innerExceptionCategory": "access_denied", "httpStatusCode": 400}
    assert "PRIVATE" not in json.dumps(proof)


@pytest.mark.parametrize(
    "damage", [{"stage": "PRIVATE"}, {"exceptionCategory": "PRIVATE"}, {"innerExceptionCategory": "PRIVATE"}, {"httpStatusCode": True}, {"httpStatusCode": 99}, {"httpStatusCode": 600}]
)
def test_unknown_native_diagnostics_are_rejected_not_silently_discarded(damage):
    with pytest.raises(diagnostic.AdmissionError):
        diagnostic.safe_native_failure({"stage": "session_create", "exceptionCategory": "io", **damage})
    assert diagnostic.safe_native_failure(None) is None


@pytest.mark.parametrize("capture", ["failure", "successful", "missing", "unknown", "wrong-placement"])
def test_exact_production_failure_path_is_preserved_without_raw_messages(tmp_path, capture):
    row = {"modelRequests": 0, "terminalState": "error"}
    body = {"completed": capture == "successful", "agentRuntimeEvidence": [row]}
    failure = {"stage": "session_create", "exceptionCategory": "io", "message": "PRIVATE", "path": "PRIVATE"}
    if capture == "failure":
        row["failure"] = failure
    elif capture == "unknown":
        row["failure"] = {**failure, "exceptionCategory": "PRIVATE"}
    elif capture == "wrong-placement":
        body["runtimeTurn"] = {"failure": failure}
    path = tmp_path / "result.json"
    path.write_text(json.dumps(body))
    if capture in ("missing", "unknown", "wrong-placement"):
        with pytest.raises(diagnostic.AdmissionError):
            diagnostic.diagnostic_transcript(path)
    else:
        safe = diagnostic.diagnostic_transcript(path)
        assert "PRIVATE" not in json.dumps(safe)
        if capture == "failure":
            assert safe["turns"][0]["failure"] == {"stage": "session_create", "exceptionCategory": "io"}
        else:
            assert "failure" not in safe["turns"][0]


def test_nonpackage_driver_uses_original_command_environment_and_independent_identity(tmp_path, monkeypatch):
    import bcal_governed_study
    from bcal_startup_fixture import offline_route

    from bcbench.agent.bcal import agent

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    pin = identity(runtime)
    manifest = tmp_path / "identity.json"
    manifest.write_text(pin.model_dump_json())
    network = tmp_path / "denial.json"
    network.write_text(
        json.dumps(
            {
                "status": "outbound-denial-active",
                "allPrograms": True,
                "allProtocols": True,
                "ipv4NonLoopbackDenied": True,
                "ipv6NonLoopbackDenied": True,
                "profilesEnabled": True,
                "externalTcpProbeBlocked": True,
                "loopbackTcpProbeAllowed": True,
                "rulesVerified": 2,
            }
        )
    )
    args = Namespace(
        runtime=runtime, identity=manifest, identity_sha256=diagnostic.sha(manifest), symbols=tmp_path / "symbols", work=tmp_path / "work", output=tmp_path / "safe", network_proof=network
    )
    monkeypatch.setattr(diagnostic.subprocess, "check_output", lambda *args, **kwargs: pin.product_version)
    monkeypatch.setattr(diagnostic, "verify_symbol_closure", lambda *args: [])
    monkeypatch.setattr(bcal_governed_study, "verify_owned_cleanup", lambda *args: None)
    for key in tuple(diagnostic.os.environ):
        if key.startswith("LLM_API_") or key in {"OPENAI_API_KEY", "AZURE_CLIENT_SECRET"}:
            monkeypatch.delenv(key)
    monkeypatch.setenv("BCAL_REASONING_LOCAL_KEY", "previous")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "PRIVATE")
    with pytest.raises(diagnostic.AdmissionError):
        diagnostic.run(args)
    monkeypatch.delenv("AZURE_CLIENT_SECRET")

    def process(command, **kwargs):
        assert diagnostic.offline_route is offline_route
        assert command[0] == str(args.work / "worker-0" / "runtime" / "bcal.exe")
        for option in ("--sdk-max-model-requests=30", "--sdk-timeout-seconds=390", "--sdk-reasoning-effort=medium", "--page=22", "--audience=Technical"):
            assert option in command
        assert kwargs["timeout"] == 420
        assert not any(key.startswith("LLM_API_") for key in kwargs["env"])
        result = next(value.split("=", 1)[1] for value in command if value.startswith("--result="))
        diagnostic.write_json(
            Path(result),
            {
                "completed": False,
                "executionIdentity": {"sourceCommitSha": pin.source_commit},
                "runtimeIdentity": {"mainModel": "gpt-56-reasoning-sol", "reasoningEffort": "medium", "sdkPackageVersion": pin.sdk_version, "sdkRuntimeVersion": pin.native_version},
                "agentRuntimeEvidence": [{"modelRequests": 0, "terminalState": "error", "failure": {"stage": "session_create", "exceptionCategory": "io"}}],
                "failure": {"code": "turn_failed", "message": "PRIVATE"},
            },
        )
        raise subprocess.CalledProcessError(1, command, output="PRIVATE")

    monkeypatch.setattr(agent, "_run_bcal_process", process)
    diagnostic.run(args)
    proof = json.loads((args.output / "nonpackage-startup-summary.json").read_bytes())
    assert proof["identity"]["kind"] == "source-built-nonpackage"
    assert proof["identity"]["packageAdmissionClaimed"] is False
    assert proof["goldAdmissionClaimed"] is False
    assert proof["providerAttempts"] == proof["judgeCalls"] == proof["auxiliaryInvocations"] == 0
    assert proof["processEvidence"]["exitCode"] == 1
    assert proof["terminalEvidence"]["turns"][0]["failure"]["stage"] == "session_create"
    assert "PRIVATE" not in json.dumps(proof)
    assert diagnostic.os.environ["BCAL_REASONING_LOCAL_KEY"] == "previous"
