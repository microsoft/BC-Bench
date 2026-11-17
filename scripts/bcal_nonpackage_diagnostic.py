"""Explicit nonpackage identity and closed native diagnostic evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import secrets
import shutil
import subprocess
from pathlib import Path, PureWindowsPath
from typing import Literal

from bcal_reasoning_coding import AdmissionError, CodingPolicy, CodingRun, coding_command, process_environment, transcript_summary, write_json
from bcal_reasoning_smoke import TASK, verify_symbol_closure
from bcal_startup_fixture import loopback_only, offline_route, verify_denial
from pydantic import BaseModel, ConfigDict, Field

NATIVE_FAILURE_STAGES = frozenset(
    (
        "validate_turn",
        "runtime_directory",
        "native_start",
        "session_create",
        "session_resume",
        "native_mode",
        "native_catalog_initialize",
        "native_catalog_read",
        "native_mode_restore",
        "native_send",
        "native_events",
        "request_admission",
        "request_decode",
        "request_policy",
        "request_transport",
        "domain_completion",
        "runtime_cleanup",
    )
)
NATIVE_FAILURE_CATEGORIES = frozenset(
    (
        "canceled",
        "timeout",
        "access_denied",
        "file_missing",
        "directory_missing",
        "native_library_missing",
        "binary_format",
        "type_initialization",
        "http",
        "socket",
        "process",
        "io",
        "json",
        "invalid_operation",
        "argument",
        "not_supported",
        "unknown",
        "http_status",
        "sdk_session_error",
    )
)


def safe_native_failure(value: object) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("stage") not in NATIVE_FAILURE_STAGES or value.get("exceptionCategory") not in NATIVE_FAILURE_CATEGORIES:
        raise AdmissionError("Native diagnostic stage or category is not admitted.")
    result = {"stage": value["stage"], "exceptionCategory": value["exceptionCategory"]}
    inner = value.get("innerExceptionCategory")
    if inner is not None:
        if inner not in NATIVE_FAILURE_CATEGORIES:
            raise AdmissionError("Native inner exception category is not admitted.")
        result["innerExceptionCategory"] = inner
    status = value.get("httpStatusCode")
    if status is not None:
        if type(status) is not int or not 100 <= status <= 599:
            raise AdmissionError("Native diagnostic HTTP status is invalid.")
        result["httpStatusCode"] = status
    return result


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class DiagnosticFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(strict=True, gt=0)


class NonpackageIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["source-built-nonpackage"] = "source-built-nonpackage"
    packageAdmissionClaimed: Literal[False] = False
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    patch_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    product_version: str = Field(min_length=1, max_length=160)
    sdk_version: str = Field(pattern=r"^\d+\.\d+\.\d+(\+[a-zA-Z0-9.-]+)?$")
    native_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    sdk_path: str
    native_path: tuple[str, ...] = Field(min_length=1)
    native_library_path: str = r"runtimes\win-x64\native\copilot_runtime.dll"
    files: tuple[DiagnosticFile, ...] = Field(min_length=5)

    @property
    def sdk_package_version(self) -> str:
        return self.sdk_version.split("+", 1)[0]

    def verify(self, runtime: Path) -> dict:
        expected = {}
        for item in self.files:
            relative = PureWindowsPath(item.path)
            canonical = ntpath.normcase(str(relative))
            if not item.path or relative.anchor or relative.drive or any(part in ("..", ".") or ":" in part or part.endswith((" ", ".")) for part in relative.parts) or canonical in expected:
                raise AdmissionError("Nonpackage inventory path is invalid or duplicated.")
            path = runtime.joinpath(*relative.parts)
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != runtime.parent):
                raise AdmissionError("Nonpackage runtime must not use symbolic links.")
            if path.stat().st_size != item.bytes or sha(path) != item.sha256:
                raise AdmissionError("Nonpackage runtime bytes differ from the immutable inventory.")
            expected[canonical] = item
        actual = {ntpath.normcase(str(PureWindowsPath(path.relative_to(runtime)))) for path in runtime.rglob("*") if path.is_file()}
        required = ("bcal.exe", "bcal.dll", ntpath.normcase(self.sdk_path), ntpath.normcase(self.native_library_path), *(ntpath.normcase(path) for path in self.native_path))
        if actual != set(expected) or len(set(required)) != len(required) or any(name not in expected for name in required):
            raise AdmissionError("Nonpackage runtime inventory or required binary roles differ.")
        version = subprocess.check_output([str(runtime / "bcal.exe"), "--version"], env=process_environment(), text=True, timeout=30).strip()
        if version != self.product_version:
            raise AdmissionError("Nonpackage CLI product version differs.")
        return {
            "kind": "source-built-nonpackage",
            "packageAdmissionClaimed": False,
            "sourceCommit": self.source_commit,
            "patchSha256": self.patch_sha256,
            "productVersion": version,
            "verifiedFiles": len(expected),
            "executableSha256": expected["bcal.exe"].sha256,
            "assemblySha256": expected["bcal.dll"].sha256,
            "sdkVersion": self.sdk_version,
            "sdkPackageVersion": self.sdk_package_version,
            "sdkSha256": expected[required[2]].sha256,
            "nativeVersion": self.native_version,
            "nativeSha256": expected[required[3]].sha256,
            "nativeLauncherSha256": [expected[path].sha256 for path in required[4:]],
        }


def load_identity(path: Path, expected_sha256: str) -> NonpackageIdentity:
    if len(expected_sha256) != 64 or sha(path) != expected_sha256:
        raise AdmissionError("Externally supplied nonpackage identity hash differs.")
    return NonpackageIdentity.model_validate(json.loads(path.read_bytes()))


def diagnostic_transcript(path: Path) -> dict:
    summary = transcript_summary(path)
    if not summary["available"]:
        raise AdmissionError("The diagnostic CLI transcript is unavailable.")
    body = json.loads(path.read_bytes())
    turns = body.get("agentRuntimeEvidence")
    if not isinstance(turns, list) or not turns or len(turns) != len(summary["turns"]):
        raise AdmissionError("Diagnostic native turn evidence is missing or malformed.")
    for raw, safe in zip(turns, summary["turns"], strict=True):
        failure = safe_native_failure(raw.get("failure"))
        if failure is not None:
            safe["failure"] = failure
    if not summary["completed"] and not any("failure" in turn for turn in summary["turns"]):
        raise AdmissionError("The failed diagnostic CLI did not expose a closed native failure.")
    return summary


def run(args: argparse.Namespace) -> None:
    from bcal_governed_study import verify_owned_cleanup
    from bcal_reasoning_coding import ProviderBudget
    from bcbench_core.git import commit_changes, init_repo

    from bcbench.agent.bcal.agent import _run_bcal_process

    denial = verify_denial(args.network_proof)
    if any(name.startswith("LLM_API_") or name in {"OPENAI_API_KEY", "AZURE_CLIENT_SECRET"} for name in os.environ):
        raise AdmissionError("Nonpackage diagnosis forbids inherited provider credentials.")
    identity = load_identity(args.identity, args.identity_sha256)
    args.output.mkdir(exist_ok=False)
    write_json(args.output / "execution-once.json", {"identitySha256": args.identity_sha256, "kind": "source-built-nonpackage", "providerAuthorized": False})
    args.work.mkdir(exist_ok=False)
    with loopback_only() as network:
        before = identity.verify(args.runtime)
        verify_symbol_closure(args.symbols)
        runtime = args.work / "worker-0" / "runtime"
        shutil.copytree(args.runtime, runtime)
        if identity.verify(runtime) != before:
            raise AdmissionError("Copied nonpackage runtime identity differs.")
        private = args.work / "000-gpt-56-reasoning-sol"
        (private / "auxiliary").mkdir(parents=True)
        exports = private / "workspace" / "smoke" / "src"
        exports.mkdir(parents=True)
        init_repo(private / "workspace")
        commit_changes(private / "workspace", "Initial AL output scaffold", allow_empty=True)
        scenario = private / "scenario.json"
        write_json(scenario, {"schemaVersion": "1.0", "steps": [{"id": "synthetic-clamp-priority", "type": "user", "text": TASK}]})
        policy = CodingPolicy(model="gpt-56-reasoning-sol", reasoning_effort="medium", auxiliary="forbid")
        config = CodingRun(policies=(policy,), max_provider_attempts=30, timeout_seconds=420, page=22, audience="Technical")
        budget = ProviderBudget(args.output / "attempts.json", 30)
        key = secrets.token_urlsafe(32)
        previous = os.environ.get("BCAL_REASONING_LOCAL_KEY")
        os.environ["BCAL_REASONING_LOCAL_KEY"] = key
        process = {"outcome": "not_started", "exitCode": None, "exceptionCategory": None}
        try:
            with offline_route(policy, budget, key) as url:
                command, _ = coding_command(runtime, args.symbols, scenario, private, policy, config, url)
                command = [value if not value.startswith("--exportfolder=") else f"--exportfolder={exports}" for value in command]
                with (private / "console.txt").open("w", encoding="utf-8") as console:
                    try:
                        result = _run_bcal_process(command, timeout=420, stdout=console, env={**process_environment(), "BCAL_REASONING_LOCAL_KEY": key})
                        process.update(outcome="completed", exitCode=result.returncode)
                    except subprocess.CalledProcessError as error:
                        process.update(outcome="nonzero_exit", exitCode=error.returncode, exceptionCategory="process_exit")
                    except subprocess.TimeoutExpired:
                        process.update(outcome="timed_out", exceptionCategory="process_timeout")
        finally:
            if previous is None:
                os.environ.pop("BCAL_REASONING_LOCAL_KEY", None)
            else:
                os.environ["BCAL_REASONING_LOCAL_KEY"] = previous
            verify_owned_cleanup(runtime / "bcal.exe")
            write_json(args.output / "process-evidence.json", process)
            if identity.verify(runtime) != before or identity.verify(args.runtime) != before:
                raise AdmissionError("Nonpackage diagnostic runtime changed during execution.")
        transcript = diagnostic_transcript(private / "result.json")
        raw = json.loads((private / "result.json").read_bytes())
        runtime_identity = raw.get("runtimeIdentity", {})
        if (
            raw.get("executionIdentity", {}).get("sourceCommitSha") != identity.source_commit
            or runtime_identity.get("mainModel") != policy.model
            or runtime_identity.get("reasoningEffort") != "medium"
            or runtime_identity.get("sdkPackageVersion") != identity.sdk_package_version
            or runtime_identity.get("sdkRuntimeVersion") != identity.native_version
            or list((private / "auxiliary").iterdir())
            or budget.events
            or network["blockedExternalConnects"]
        ):
            raise AdmissionError("Nonpackage diagnostic execution identity or zero-provider boundary differs.")
    write_json(
        args.output / "nonpackage-startup-summary.json",
        {
            "status": "diagnostic-complete",
            "identity": before,
            "identitySha256": args.identity_sha256,
            "benchCommit": os.environ.get("GITHUB_SHA"),
            "providerAttempts": 0,
            "judgeCalls": 0,
            "auxiliaryInvocations": 0,
            "processEvidence": process,
            "terminalEvidence": transcript,
            "networkDenial": denial,
            "parentSocketGuard": network,
            "runtimeCleanupVerified": True,
            "runtimeBytesUnchanged": True,
            "domainPass": False,
            "goldAdmissionClaimed": False,
            "rawMessagesRetained": False,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runtime", "identity", "symbols", "work", "output", "network-proof"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--identity-sha256", required=True)
    args = parser.parse_args()
    try:
        run(args)
    except Exception:  # noqa: BLE001 - never emit private native startup messages or local artifact paths
        write_json(args.output.parent / "nonpackage-diagnostic-failure.json", {"status": "diagnostic-stopped", "rawMessageRetained": False})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
