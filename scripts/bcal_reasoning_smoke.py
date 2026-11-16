"""Once-only three-model actual coding smoke; no judge, gold, or retry."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from bcal_reasoning_coding import PACKAGE_SOURCE, AdmissionError, CodingPolicy, CodingRun, coding_command, process_environment, verify_auxiliary_command
from bcal_reasoning_compatibility import CLIENT_SHA, MODELS, load_module, native_probe, verify_package, write_json

ROOT = Path(__file__).resolve().parents[1]
SYMBOL_MANIFEST_SHA = "cee5605b0cb36d894c3f723d4942c8d78053b07cd31151f61e78c78aa7bf6399"
SYMBOL_PATHS = (
    r"platform\ModernDev\PFiles\Microsoft Dynamics NAV\280\AL Development Environment\System.app",
    r"w1\Extensions\Microsoft_Application_28.0.46665.57479.app",
    r"w1\Extensions\Microsoft_Base Application_28.0.46665.57479.app",
    r"w1\Extensions\Microsoft_System Application_28.0.46665.57479.app",
    r"w1\Extensions\Microsoft_Business Foundation_28.0.46665.57479.app",
)
TASK = (
    "This is a new synthetic coding smoke, not a benchmark dataset case. "
    'Create a standalone AL codeunit named "Reasoning Smoke Priority", using a vacant allowed custom object ID '
    "(prefer 50149 only if it is available). "
    "Implement public procedure ClampPriority(Value: Integer): Integer. "
    "Return 0 when Value is below 0, return 9 when it is above 9, otherwise return Value. "
    "Use only local AL source authoring. Do not read or write business records, connect to a server, "
    "publish, deploy, execute AL, or modify any existing object. "
    "Compile the latest generated source and finish with the AL source exported."
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AdmissionError(message)


def smoke_config(model: str) -> CodingRun:
    return CodingRun(
        policies=(CodingPolicy(model=model, reasoning_effort="medium", auxiliary="forbid"),),
        max_provider_attempts=30,
        timeout_seconds=420,
        page=22,
    )


def verify_symbol_closure(directory: Path) -> list[dict]:
    identities = {}
    for path in directory.glob("*.app"):
        with zipfile.ZipFile(path) as outer:
            if "readytorunappmanifest.json" in outer.namelist():
                embedded = json.loads(outer.read("readytorunappmanifest.json"))["EmbeddedAppFileName"]
                with zipfile.ZipFile(io.BytesIO(outer.read(embedded))) as inner:
                    data = inner.read("NavxManifest.xml")
            else:
                data = outer.read("NavxManifest.xml")
        root = ET.fromstring(data)
        app = next(item for item in root.iter() if item.tag.rsplit("}", 1)[-1] == "App")
        dependencies = [{"id": item.attrib["Id"], "minimumVersion": item.attrib["MinVersion"]} for item in root.iter() if item.tag.rsplit("}", 1)[-1] == "Dependency"]
        require(app.attrib["Id"] not in identities, "Duplicate symbol application identity.")
        identities[app.attrib["Id"]] = {
            "id": app.attrib["Id"],
            "version": app.attrib["Version"],
            "platformMinimum": app.attrib.get("Platform"),
            "dependencies": dependencies,
        }
    platform = identities.get("8874ed3a-0643-4247-9ced-7a7002f7135d")
    require(platform is not None, "Required platform symbol is absent.")
    for app in identities.values():
        if app["platformMinimum"]:
            require(tuple(map(int, platform["version"].split("."))) >= tuple(map(int, app["platformMinimum"].split("."))), "Platform version does not cover dependency closure.")
        for dependency in app["dependencies"]:
            target = identities.get(dependency["id"])
            require(target is not None, "Transitive symbol dependency is absent.")
            require(tuple(map(int, target["version"].split("."))) >= tuple(map(int, dependency["minimumVersion"].split("."))), "Transitive symbol dependency version differs.")
    return sorted(identities.values(), key=lambda row: row["id"])


def materialize_symbols(cache: Path, destination: Path) -> dict:
    manifest_path = ROOT / "experiments" / "bcal-sdk-policy" / "symbols.json"
    if sha(manifest_path) != SYMBOL_MANIFEST_SHA:
        raise AdmissionError("Frozen symbol manifest differs.")
    manifest = json.loads(manifest_path.read_bytes())
    if len(manifest["files"]) != 350:
        raise AdmissionError("Expected exactly350 local symbol archives.")
    destination.mkdir(parents=True, exist_ok=False)
    names: set[str] = set()
    selected = [row for row in manifest["files"] if row["path"] in SYMBOL_PATHS]
    require(len(selected) == len(SYMBOL_PATHS), "Exact standalone-coding dependency symbols are missing.")
    for row in selected:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.name in names:
            raise AdmissionError("Invalid or colliding frozen symbol path.")
        names.add(relative.name)
        source = cache / manifest["cacheVersion"] / relative
        if sha(source) != row["sha256"] or source.stat().st_size != row["bytes"]:
            raise AdmissionError("Frozen symbol payload differs.")
        shutil.copyfile(source, destination / relative.name)
    return {"count": len(selected), "manifestSha256": SYMBOL_MANIFEST_SHA, "selectedFiles": selected, "dependencyClosure": verify_symbol_closure(destination)}


def admit_actual_executable(args: argparse.Namespace) -> dict:
    from bcal_governed_study import verify_owned_cleanup

    from bcbench.agent.bcal.agent import _run_bcal_process

    policy = smoke_config(MODELS[0]).policies[0]
    run = smoke_config(MODELS[0]).model_copy(update={"max_provider_attempts": 1, "timeout_seconds": 90})
    private = args.work / "offline-executable"
    (private / "auxiliary").mkdir(parents=True)
    proxy = load_module("smoke_offline_cli_proxy", ROOT / "src" / "bcbench" / "agent" / "bcal" / "bc_eval_sdk_proxy.py")
    receipt = {"providerAttempts": 0, "offlineRequests": 0, "localBlocked": 0, "productionWireObserved": False}

    class Response:
        status_code = 400
        headers: ClassVar = {"content-type": "application/json"}

        def iter_bytes(self) -> Iterator[bytes]:
            yield b'{"error":{"message":"Offline admission only"}}'

    @contextmanager
    def forward(route: str, body: dict) -> Iterator[Response]:
        if receipt["offlineRequests"]:
            receipt["localBlocked"] += 1
            raise proxy.ProxyError("No second offline admission request.")
        policy.verify_wire(body)
        require(isinstance(body.get("tools"), list) and len(body["tools"]) > 1, "Actual packaged CLI did not expose its normal tool catalog.")
        receipt.update(
            offlineRequests=1,
            productionWireObserved=True,
            model=body["model"],
            wireEffort="medium",
            toolCount=len(body["tools"]),
            wireToolCatalogSha256=hashlib.sha256(json.dumps(body["tools"], sort_keys=True).encode()).hexdigest(),
        )
        yield Response()

    with ThreadingHTTPServer(("127.0.0.1", 0), proxy._handler("offline-key", policy.model, "responses", forward)) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        previous = os.environ.get("BCAL_REASONING_LOCAL_KEY")
        os.environ["BCAL_REASONING_LOCAL_KEY"] = "offline-key"
        try:
            command, _ = coding_command(args.package, args.work / "symbols", args.work / "scenario.json", private, policy, run, f"http://127.0.0.1:{server.server_port}")
            with (private / "console.txt").open("w", encoding="utf-8") as console:
                try:
                    _run_bcal_process(command, timeout=120, stdout=console, env={**process_environment(), "BCAL_REASONING_LOCAL_KEY": "offline-key"})
                except subprocess.CalledProcessError:
                    receipt["expectedOfflineFailure"] = True
                except subprocess.TimeoutExpired:
                    receipt["failureCategory"] = "offline_process_timeout"
        finally:
            server.shutdown()
            thread.join()
            if previous is None:
                os.environ.pop("BCAL_REASONING_LOCAL_KEY", None)
            else:
                os.environ["BCAL_REASONING_LOCAL_KEY"] = previous
            verify_owned_cleanup(args.package / "bcal.exe")
            write_json(args.output / "offline-executable.json", receipt)
    require(receipt["productionWireObserved"] and receipt.get("expectedOfflineFailure") is True, "Actual packaged CLI first-request admission failed.")
    require(not any((private / "auxiliary").iterdir()), "Actual packaged CLI invoked forbidden auxiliary inference during admission.")
    return receipt


def admit(args: argparse.Namespace) -> None:
    import importlib.metadata

    args.work.mkdir(parents=True, exist_ok=False)
    args.output.mkdir(parents=True, exist_ok=False)
    verified = verify_package(args.package, args.archive)
    version = subprocess.check_output([str(args.package / "bcal.exe"), "--version"], env=process_environment(), text=True, timeout=30).strip()
    if version != "30.0.46.49019+" + PACKAGE_SOURCE:
        raise AdmissionError("Actual packaged CLI version differs.")
    client_source = Path(importlib.metadata.distribution("bc-eval").locate_file("bc_eval/llm/llm_api.py"))
    if sha(client_source) != CLIENT_SHA:
        raise AdmissionError("Pinned provider client differs.")
    symbols = materialize_symbols(args.symbol_cache, args.work / "symbols")
    scenario = args.work / "scenario.json"
    write_json(scenario, {"schemaVersion": "1.0", "steps": [{"id": "synthetic-clamp-priority", "type": "user", "text": TASK}]})
    verify_auxiliary_command(process_environment())
    receipts = []
    for model in MODELS:
        config = args.work / f"{model}.config.json"
        config.write_text(smoke_config(model).model_dump_json(indent=2), encoding="utf-8")
        proof = native_probe(args.package, args.helper, model, "medium", "offline", args.output / f"offline-{model}.json", "offline")
        wire = proof.get("wire", {})
        if (
            proof.get("outcome") != "response_received"
            or proof.get("boundaryRequests") != 1
            or proof.get("boundaryBlocked") != 0
            or proof.get("appliedEffort") != "medium"
            or wire.get("model") != model
            or wire.get("reasoning", {}).get("effort") != "medium"
        ):
            raise AdmissionError("Current packaged native medium wire admission failed before any provider call.")
        receipts.append({"model": model, "configSha256": sha(config), "proofSha256": sha(args.output / f"offline-{model}.json")})
    executable = admit_actual_executable(args)
    write_json(args.output / "offline-executable.json", executable)
    write_json(
        args.output / "admission.json",
        {
            "status": "offline-admitted",
            "benchCommit": os.environ.get("GITHUB_SHA"),
            "pythonVersion": sys.version.split()[0],
            "packageVersion": version,
            "verifiedRuntimeFiles": verified,
            "symbols": symbols,
            "scenarioSha256": sha(scenario),
            "runnerSha256": sha(Path(__file__)),
            "codingRunnerSha256": sha(ROOT / "scripts" / "bcal_reasoning_coding.py"),
            "helperSha256": sha(args.helper),
            "models": receipts,
            "perModelProviderAttemptCap": 30,
            "totalProviderAttemptCap": 90,
            "providerAttempts": 0,
            "nativeAdmissionScope": "Packaged SDK/full handler synthetic offline request; live coding uses unmodified production prompt/tools.",
            "actualExecutableAdmissionSha256": sha(args.output / "offline-executable.json"),
            "judge": "prohibited",
            "auxiliary": "prohibited",
            "retries": "prohibited",
            "replacement": "prohibited",
        },
    )


def validate_admission(args: argparse.Namespace) -> dict:
    value = json.loads((args.output / "admission.json").read_bytes())
    if (
        value["status"] != "offline-admitted"
        or value["benchCommit"] != os.environ.get("GITHUB_SHA")
        or value["runnerSha256"] != sha(Path(__file__))
        or value["codingRunnerSha256"] != sha(ROOT / "scripts" / "bcal_reasoning_coding.py")
        or value["helperSha256"] != sha(args.helper)
        or value["scenarioSha256"] != sha(args.work / "scenario.json")
        or [row["model"] for row in value["models"]] != list(MODELS)
        or value["actualExecutableAdmissionSha256"] != sha(args.output / "offline-executable.json")
    ):
        raise AdmissionError("Current source or offline admission binding differs.")
    verify_package(args.package, args.archive)
    for row in value["models"]:
        model = row["model"]
        path = args.work / f"{model}.config.json"
        if sha(path) != row["configSha256"] or CodingRun.model_validate_json(path.read_bytes()) != smoke_config(model):
            raise AdmissionError("Once-only model configuration changed.")
        if sha(args.output / f"offline-{model}.json") != row["proofSha256"]:
            raise AdmissionError("Native offline effort proof changed.")
    # Recheck the actual flattened symbol files before any provider request.
    for row in value["symbols"]["selectedFiles"]:
        if sha(args.work / "symbols" / Path(row["path"]).name) != row["sha256"]:
            raise AdmissionError("Admitted symbol bytes changed.")
    return value


def execute(args: argparse.Namespace) -> None:
    from bcal_governed_study import verify_owned_cleanup

    from bcbench.agent.bcal.agent import _run_bcal_process

    admission = validate_admission(args)
    # This marker is exclusive and is never removed, even if execution fails.
    with (args.output / "execution-once.json").open("x", encoding="utf-8") as file:
        json.dump({"runId": os.environ.get("GITHUB_RUN_ID"), "sourceSha": os.environ.get("GITHUB_SHA"), "startedAtUtc": datetime.now(UTC).isoformat()}, file)
    matrix = {
        "status": "running",
        "admission": admission,
        "models": [],
        "providerAttempts": 0,
        "perModelProviderAttemptCap": 30,
        "totalProviderAttemptCap": 90,
        "judgeCalls": 0,
        "cost": None,
    }
    write_json(args.output / "matrix.json", matrix)
    try:
        for model in MODELS:
            require(matrix["providerAttempts"] <= 60, "Full remaining per-model reservation is unavailable.")
            private = args.work / f"{model}.execution"
            command = [
                sys.executable,
                str(ROOT / "scripts" / "bcal_reasoning_coding.py"),
                "coding",
                "--config",
                str(args.work / f"{model}.config.json"),
                "--package",
                str(args.package),
                "--archive",
                str(args.archive),
                "--symbols",
                str(args.work / "symbols"),
                "--scenario",
                str(args.work / "scenario.json"),
                "--output",
                str(private),
                "--execute",
            ]
            process = {"completed": False, "exitCode": None, "failureCategory": None}
            try:
                with (args.work / f"{model}.console.txt").open("w", encoding="utf-8") as console:
                    _run_bcal_process(command, timeout=480, stdout=console, env=dict(os.environ))
                process.update(completed=True, exitCode=0)
            except subprocess.CalledProcessError as error:
                process.update(completed=True, exitCode=error.returncode, failureCategory="command_exit")
            except subprocess.TimeoutExpired:
                process["failureCategory"] = "timeout"
            finally:
                verify_owned_cleanup(args.package / "bcal.exe")
            receipt_path, ledger_path = private / "receipt.json", private / "provider-attempts.json"
            require(receipt_path.is_file() and ledger_path.is_file(), "Coding subprocess lacks auditable receipts; stop remaining admissions.")
            receipt, ledger = json.loads(receipt_path.read_bytes()), json.loads(ledger_path.read_bytes())
            events = ledger["events"]
            require(
                ledger["limit"] == 30 and ledger["attempts"] == len(events) and len(events) <= 30 and all(event["model"] == model and event["role"] == "main" for event in events),
                "Actual per-model attempt accounting differs.",
            )
            matrix["providerAttempts"] += ledger["attempts"]
            require(matrix["providerAttempts"] <= 90, "Total attempt cap was violated.")
            shutil.copyfile(receipt_path, args.output / f"{model}.receipt.json")
            shutil.copyfile(ledger_path, args.output / f"{model}.attempts.json")
            matrix["models"].append(
                {
                    "model": model,
                    "status": receipt["status"],
                    "process": process,
                    "providerAttempts": ledger["attempts"],
                    "receiptSha256": sha(receipt_path),
                    "ledgerSha256": sha(ledger_path),
                }
            )
            write_json(args.output / "matrix.json", matrix)
        matrix["status"] = "completed" if all(row["status"] == "completed" for row in matrix["models"]) else "completed-with-failures"
    except Exception:
        matrix["status"] = "infrastructure-failed"
        raise
    finally:
        matrix["finishedAtUtc"] = datetime.now(UTC).isoformat()
        write_json(args.output / "matrix.json", matrix)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("admit", "execute"))
    for name in ("package", "archive", "helper", "symbol-cache", "work", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        {"admit": admit, "execute": execute}[args.phase](args)
    except Exception as error:  # noqa: BLE001 - no private provider/package details in public logs
        sys.stderr.write(f"Once-only coding smoke stopped: {type(error).__name__}\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
