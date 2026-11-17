import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bcal_diagnostic_console as console


def inputs(tmp_path):
    output = tmp_path / "execution"
    output.mkdir()
    cleanup = tmp_path / "cleanup.json"
    cleanup.write_text(
        json.dumps(
            dict.fromkeys(("denialRulesRemoved", "dnsConfigurationUnchanged", "dnsCacheCleared", "dnsProbeSucceeded", "runtimeProcessCleanupVerified"), True)
            | {"providerCredentialsFetched": False, "privatePath": "PRIVATE"}
        )
    )
    (tmp_path / "diagnostic-driver-stage.json").write_text(
        json.dumps({"status": "failed", "stage": "runtime_cleanup", "failureStage": "cli_process", "exceptionCategory": "type", "message": "PRIVATE"})
    )
    return output, cleanup


def test_console_preserves_partial_failure_and_cleanup_when_artifact_upload_is_unavailable(tmp_path):
    output, cleanup = inputs(tmp_path)
    safe = console.receipt(output, cleanup)
    assert safe["status"] == "partial"
    assert safe["driver"]["failureStage"] == "cli_process"
    assert safe["cleanup"]["denialRulesRemoved"] is True
    assert "PRIVATE" not in json.dumps(safe)
    assert "counters" not in safe


@pytest.mark.parametrize("damage", ["none", "projection", "code", "failure", "cleanup", "journal"])
def test_console_validates_all_exported_fields_and_never_leaks_raw_content(tmp_path, damage):
    output, cleanup = inputs(tmp_path)
    body = {
        "benchCommit": "a" * 40,
        "startupFailureProjection": {"evidenceSource": "scenario_failure_message", "nativeFailureKind": "session_ownership", "nativeErrorCode": 183},
        "terminalEvidence": {
            "turns": [{"modelRequests": 0, "responseIterations": 0, "toolCalls": 0, "usageEvents": 0, "failure": {"stage": "session_create", "exceptionCategory": "io", "message": "PRIVATE"}}]
        },
        "providerAttempts": 0,
        "auxiliaryInvocations": 0,
        "judgeCalls": 0,
        "rawMessage": "PRIVATE",
    }
    if damage == "projection":
        body["startupFailureProjection"]["rawMessage"] = "PRIVATE"
    elif damage == "code":
        body["startupFailureProjection"]["nativeErrorCode"] = True
    elif damage == "failure":
        body["terminalEvidence"]["turns"][0]["failure"]["stage"] = "PRIVATE"
    elif damage == "cleanup":
        cleanup.write_text(json.dumps({"denialRulesRemoved": "true"}))
    elif damage == "journal":
        (tmp_path / "diagnostic-driver-stage.json").write_text(json.dumps({"status": "failed", "stage": "PRIVATE"}))
    (output / "package-startup-summary.json").write_text(json.dumps(body))
    if damage == "none":
        safe = console.receipt(output, cleanup)
        assert safe["startupFailureProjection"]["nativeErrorCode"] == 183
        assert safe["nativeFailure"] == {"stage": "session_create", "exceptionCategory": "io"}
        assert "PRIVATE" not in json.dumps(safe)
    else:
        with pytest.raises(console.AdmissionError):
            console.receipt(output, cleanup)
