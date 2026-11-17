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
    "damage", ["none", "same-package-projection", "unchanged-projection", "missing-id", "path", "id-hash", "same-package", "hypothesis", "not-ready", "identity-bytes", "prior-dispatch", "rerun"]
)
def test_actual_workflow_admits_only_fresh_ready_identity_once(tmp_path, damage):
    source = "e" * 40
    archive = "a" * 64
    attempt = "build-123-" + archive[:12]
    projection = damage in ("same-package-projection", "unchanged-projection")
    if projection:
        attempt += "-projection1"
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
    if damage in ("none", "same-package-projection"):
        assert result.returncode == 0, result.stderr
        assert "version=30.0.46.99999-beta" in (tmp_path / "outputs.txt").read_text()
        assert attempt in (tmp_path / "outputs.txt").read_text()
    else:
        assert result.returncode != 0
        assert not (tmp_path / "outputs.txt").exists()
