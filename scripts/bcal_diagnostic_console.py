"""Emit closed post-cleanup diagnostics independently of artifact upload."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from bcal_nonpackage_diagnostic import safe_native_failure
from bcal_package_diagnostic import DRIVER_CATEGORIES, DRIVER_STAGES
from bcal_reasoning_coding import AdmissionError


def load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise AdmissionError("Diagnostic console input is malformed.")
    return value


def receipt(output: Path, cleanup_path: Path) -> dict:
    cleanup = load(cleanup_path)
    if cleanup is None:
        raise AdmissionError("Cleanup evidence is required before console emission.")
    safe_cleanup = {}
    for key in ("denialRulesRemoved", "providerCredentialsFetched", "dnsConfigurationUnchanged", "dnsCacheCleared", "dnsProbeSucceeded", "runtimeProcessCleanupVerified"):
        if type(cleanup.get(key)) is not bool:
            raise AdmissionError("Closed cleanup boolean is missing.")
        safe_cleanup[key] = cleanup[key]
    journal = load(output.parent / "diagnostic-driver-stage.json")
    safe_journal = None
    if journal is not None:
        if journal.get("status") not in ("running", "failed", "completed") or journal.get("stage") not in DRIVER_STAGES:
            raise AdmissionError("Unknown diagnostic driver state.")
        safe_journal = {"status": journal["status"], "stage": journal["stage"]}
        if "failureStage" in journal:
            if journal["failureStage"] not in DRIVER_STAGES or journal.get("exceptionCategory") not in DRIVER_CATEGORIES:
                raise AdmissionError("Unknown diagnostic failure category.")
            safe_journal.update(failureStage=journal["failureStage"], exceptionCategory=journal["exceptionCategory"])
    summary = load(output / "package-startup-summary.json")
    result = {"evidenceSource": "post_cleanup_console", "status": "partial" if summary is None else "complete", "cleanup": safe_cleanup, "driver": safe_journal}
    if summary is not None:
        source = summary.get("benchCommit")
        if not isinstance(source, str) or re.fullmatch(r"[a-f0-9]{40}", source) is None:
            raise AdmissionError("Console diagnostic source is malformed.")
        projection = summary.get("startupFailureProjection")
        if not isinstance(projection, dict) or set(projection) - {"evidenceSource", "nativeFailureKind", "nativeErrorCode"} or projection.get("evidenceSource") != "scenario_failure_message":
            raise AdmissionError("Console startup projection is malformed.")
        if "nativeFailureKind" in projection and projection["nativeFailureKind"] not in ("session_ownership", "session_construction"):
            raise AdmissionError("Unknown console native failure kind.")
        if "nativeErrorCode" in projection and (type(projection["nativeErrorCode"]) is not int or not 0 <= projection["nativeErrorCode"] <= 65535):
            raise AdmissionError("Console native error code is invalid.")
        terminal = summary.get("terminalEvidence", {})
        turns = terminal.get("turns")
        if not isinstance(turns, list) or len(turns) != 1 or not isinstance(turns[0], dict):
            raise AdmissionError("Console native turn is unavailable.")
        counters = {}
        for key in ("modelRequests", "responseIterations", "toolCalls", "usageEvents"):
            value = turns[0].get(key)
            if type(value) is not int or value < 0:
                raise AdmissionError("Console native counter is invalid.")
            counters[key] = value
        for key in ("providerAttempts", "auxiliaryInvocations", "judgeCalls"):
            if type(summary.get(key)) is not int or summary[key] != 0:
                raise AdmissionError("Console zero-provider boundary differs.")
            counters[key] = 0
        result.update(benchSource=source, nativeFailure=safe_native_failure(turns[0].get("failure")), startupFailureProjection=projection, counters=counters)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cleanup", type=Path, required=True)
    args = parser.parse_args()
    try:
        value = receipt(args.output, args.cleanup)
    except Exception:  # noqa: BLE001 - malformed private inputs must never expose raw content
        sys.stdout.write('BCAL_SAFE_DIAGNOSTIC {"status":"console_schema_rejected","evidenceSource":"post_cleanup_console"}\n')
        raise SystemExit(1) from None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    (args.output.parent / "console-diagnostic.json").write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    sys.stdout.write("BCAL_SAFE_DIAGNOSTIC " + json.dumps(value, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
