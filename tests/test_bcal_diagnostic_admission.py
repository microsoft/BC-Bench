import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")


@pytest.mark.skipif(PWSH is None, reason="Actual hosted admission requires PowerShell.")
@pytest.mark.parametrize(
    "damage",
    [
        "none",
        "same-package-projection",
        "same-package-recovery",
        "same-package-markers",
        "unchanged-markers",
        "wrong-marker-prior-run",
        "same-package-sdk",
        "sdk-send-allowed",
        "sdk-negative-allowed",
        "sdk-source-differs",
        "unchanged-projection",
        "missing-id",
        "path",
        "id-hash",
        "same-package",
        "hypothesis",
        "not-ready",
        "identity-bytes",
        "prior-dispatch",
        "rerun",
    ],
)
def test_actual_workflow_admits_only_fresh_ready_identity_once(tmp_path, damage):
    source = "e" * 40
    archive = "a" * 64
    attempt = "build-123-" + archive[:12]
    marker_probe = damage in ("same-package-markers", "unchanged-markers", "wrong-marker-prior-run")
    sdk_control = damage in ("same-package-sdk", "sdk-send-allowed", "sdk-negative-allowed", "sdk-source-differs")
    projection = damage in ("same-package-projection", "same-package-recovery", "unchanged-projection") or marker_probe or sdk_control
    if projection:
        attempt += "-sdkcontrol1" if sdk_control else "-markers1" if marker_probe else "-recovery1" if damage == "same-package-recovery" else "-projection1"
    profile = tmp_path / "experiments" / "bcal-startup-diagnostic" / "attempts" / attempt
    profile.mkdir(parents=True)

    def save(name, value):
        raw = json.dumps(value).encode()
        (profile / name).write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    identity = {"kind": "exact-diagnostic-package", "source_commit": source, "build_id": 123, "version": "30.0.46.99999-beta", "archive_sha256": archive, "feed": "DynamicsSMBTest"}
    proof = {
        "ownerReady": True,
        "packagedOfflineProofsVerified": True,
        "providerAttempts": 0,
        "sourceCommit": source,
        "buildId": 123,
        "archiveSha256": archive,
        "attemptId": attempt,
        "hypothesis": "session_create_diagnostic_boundary",
        "priorRunId": "44063403715",
        "priorArchiveSha256": archive if damage == "same-package" or projection else "b" * 64,
    }
    if damage == "hypothesis":
        proof["hypothesis"] = "PRIVATE/raw/unbounded message"
    admission = {
        "status": "not-ready" if damage == "not-ready" else "owner-ready",
        "sourceCommit": source,
        "buildId": 123,
        "identitySha256": save("package.json", identity),
        "ownerProofSha256": save("owner-proof-admission.json", proof),
        "providerAuthorized": False,
        "smokeAuthorized": False,
        "goldAuthorized": False,
        "attemptId": attempt,
    }
    if projection:
        proof["diagnosticRevision"] = admission["diagnosticRevision"] = "startup-failure-projection-v1"
        proof["priorDiagnosticRevision"] = "startup-failure-projection-v1" if damage == "unchanged-projection" else "native-failure-only"
        if damage == "same-package-recovery":
            proof["diagnosticRevision"] = admission["diagnosticRevision"] = "startup-failure-projection-v2-recovery"
            proof["priorDiagnosticRevision"] = "startup-failure-projection-v1"
            proof["priorRunId"] = "44065963616"
        if marker_probe:
            proof["diagnosticRevision"] = admission["diagnosticRevision"] = "startup-failure-projection-v3-markers"
            proof["priorDiagnosticRevision"] = "startup-failure-projection-v3-markers" if damage == "unchanged-markers" else "startup-failure-projection-v2-recovery"
            proof["priorRunId"] = "44068523635" if damage != "wrong-marker-prior-run" else "44065963616"
        if sdk_control:
            proof["diagnosticRevision"] = admission["diagnosticRevision"] = "public-sdk-create-session-control-v1"
            proof.update(
                priorDiagnosticRevision="startup-failure-projection-v3-markers",
                priorRunId="44070392112",
                hostedArguments=3,
                hostedInvocationLimit=1,
                modelSendAllowed=damage == "sdk-send-allowed",
                negativeHostedCaseAllowed=damage == "sdk-negative-allowed",
                controlSourceReadySha256="2a77001c7836bc0e6653bb7bb49efa7712f7de2d554a8a43b0da2a1af56128fa",
                controlProgramSha256="0" * 64 if damage == "sdk-source-differs" else "587988cdf27f79c0392af8530cfad25703908d75f9e2a1236374f749fccbbf4c",
                controlProjectSha256="4e6565af94d426fb3df0b85a0aa8372d10a45ef2f810a988bd469945b14c8cbc",
            )
        admission["ownerProofSha256"] = save("owner-proof-admission.json", proof)
    save("admission.json", admission)
    if damage == "identity-bytes":
        with (profile / "package.json").open("ab") as file:
            file.write(b" ")
    if damage == "id-hash":
        alternate = attempt[:-1] + "b"
        profile.rename(profile.with_name(alternate))
        attempt = alternate
    suffix = " / reasoning-package-diagnostic " + attempt
    runs = {"total_count": 1 if damage == "prior-dispatch" else 0, "workflow_runs": [{"id": 987, "display_title": suffix}] if damage == "prior-dispatch" else []}
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "bcal-package-startup.yml").read_text())
    body = next(step["run"] for step in workflow["jobs"]["diagnose"]["steps"] if step.get("id") == "admission")
    script = tmp_path / "admit.ps1"
    script.write_text(
        "function gh { '" + json.dumps(runs) + "' }\n" + body,
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "DIAGNOSTIC_ATTEMPT_ID": "" if damage == "missing-id" else "../outside" if damage == "path" else attempt,
        "REQUIRE_DIAGNOSTIC_ATTEMPT_ID": "true",
        "GITHUB_RUN_ATTEMPT": "2" if damage == "rerun" else "1",
        "GITHUB_RUN_ID": "123456",
        "GITHUB_REF_NAME": "synthetic-branch",
        "GITHUB_OUTPUT": str(tmp_path / "outputs.txt"),
    }
    result = subprocess.run([PWSH, "-NoProfile", "-File", str(script)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30, check=False)
    if damage in ("none", "same-package-projection", "same-package-recovery", "same-package-markers", "same-package-sdk"):
        assert result.returncode == 0, result.stderr
        assert "version=30.0.46.99999-beta" in (tmp_path / "outputs.txt").read_text()
        assert attempt in (tmp_path / "outputs.txt").read_text()
        assert ("sdk-control=true" in (tmp_path / "outputs.txt").read_text()) is sdk_control
    else:
        assert result.returncode != 0
        assert not (tmp_path / "outputs.txt").exists()


@pytest.mark.skipif(PWSH is None, reason="Actual hosted cleanup requires PowerShell.")
@pytest.mark.parametrize("dns_fails", [False, True])
@pytest.mark.parametrize("sdk_control", [False, True])
def test_actual_finally_restores_host_and_emits_evidence_despite_fixture_failure(tmp_path, dns_fails, sdk_control):
    wrapper = (ROOT / "scripts" / "Run-BCalStartupFixture.ps1").read_text()
    final = wrapper.rsplit("} finally {", 1)[1].rsplit("}", 1)[0]
    script = tmp_path / "cleanup.ps1"
    setup = r"""
$ErrorActionPreference = 'Stop'
$script:removed = $false
$script:cacheCleared = $false
$script:stopped = @()
function Get-NetFirewallRule { if (-not $script:removed) { [pscustomobject]@{Name='synthetic'} } }
function Remove-NetFirewallRule { $script:removed = $true }
function Get-CimInstance {
    if ($env:SYNTHETIC_SDK_CONTROL -ne 'true') { return }
    @(
        [pscustomobject]@{ProcessId=42420;ExecutablePath=(Join-Path $Work 'runtime\native.exe');CommandLine='owned-native'},
        [pscustomobject]@{ProcessId=42421;ExecutablePath=(Get-Command dotnet).Source;CommandLine=('dotnet "' + (Join-Path $Work 'control\SdkStartupControl.dll') + '" runtime state receipt')},
        [pscustomobject]@{ProcessId=42422;ExecutablePath=(Get-Command dotnet).Source;CommandLine='dotnet unrelated.dll'}
    ) | Where-Object { $_.ProcessId -notin $script:stopped }
}
function Stop-Process {
    param($Id)
    if ($Id -notin @(42420,42421)) { throw 'An unrelated simulated process was targeted.' }
    $script:stopped += $Id
}
function Get-DnsClientServerAddress { [pscustomobject]@{InterfaceIndex=1;AddressFamily=2;ServerAddresses=@('synthetic')} }
function Clear-DnsClientCache { $script:cacheCleared = $true }
function Resolve-DnsName { if ($env:SYNTHETIC_DNS_FAILS -eq 'true') { throw 'Synthetic DNS failure' }; 'synthetic' }
function Test-ConsoleEmitter {
    if (-not $script:removed -or -not $script:cacheCleared) { throw 'Console emitted before restoration.' }
    if ($env:SYNTHETIC_SDK_CONTROL -eq 'true' -and (@($script:stopped).Count -ne 2 -or (Test-Path -LiteralPath (Join-Path $Work 'sdk-state')))) { throw 'SDK host/state cleanup was not verified.' }
    Write-Output 'BCAL_SAFE_DIAGNOSTIC synthetic-after-restoration'
}
$PSCmdlet = [pscustomobject]@{ParameterSetName='DiagnosticPackage'}
$Python = 'Test-ConsoleEmitter'
$Work = Join-Path $env:RUNNER_TEMP 'owned'
if ($env:SYNTHETIC_SDK_CONTROL -eq 'true') {
    $PSCmdlet.ParameterSetName = 'SdkControl'
    New-Item -ItemType Directory -Path (Join-Path $Work 'sdk-state') | Out-Null
}
$Output = Join-Path $env:RUNNER_TEMP 'safe'
$group = 'synthetic-owned-group'
$proof = @{status='outbound-denial-active'}
$dnsBefore = @(Get-DnsClientServerAddress | Sort-Object InterfaceIndex, AddressFamily | Select-Object InterfaceIndex, AddressFamily, ServerAddresses) | ConvertTo-Json -Depth 5 -Compress
try { throw 'Synthetic fixture failure' } finally {
"""
    script.write_text(setup + final + "\n}\n", encoding="utf-8")
    result = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(script)],
        env={**os.environ, "RUNNER_TEMP": str(tmp_path), "SYNTHETIC_DNS_FAILS": str(dns_fails).lower(), "SYNTHETIC_SDK_CONTROL": str(sdk_control).lower()},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "BCAL_SAFE_DIAGNOSTIC synthetic-after-restoration" in result.stdout
    cleanup = json.loads((tmp_path / "startup-network-cleanup.json").read_bytes())
    assert cleanup["denialRulesRemoved"] is cleanup["runtimeProcessCleanupVerified"] is cleanup["dnsConfigurationUnchanged"] is cleanup["dnsCacheCleared"] is True
    assert cleanup["dnsProbeSucceeded"] is not dns_fails
    if sdk_control:
        assert cleanup["controlOwnedStateRemoved"] is True
