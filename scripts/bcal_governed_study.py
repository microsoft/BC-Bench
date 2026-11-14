"""Bounded same-package policy validation; usable locally without GitHub Actions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "experiments" / os.environ.get("BCAL_STUDY_PROFILE", "bcal-sdk-policy")
MODEL_FAILURE_STAGES = frozenset({"unknown", "command_start", "command_io", "command_exit", "response_json", "response_choices", "response_message"})
MODEL_FAILURE_CATEGORIES = frozenset({"unknown", "canceled", "json", "process", "io", "invalid_operation", "argument"})


def symbols_manifest() -> Path:
    config = study_manifest()
    return ROOT / config["symbolsManifestFile"] if "symbolsManifestFile" in config else INPUTS / "symbols.json"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def study_manifest() -> dict:
    value = json.loads((INPUTS / "study.json").read_bytes())
    if "baselineStudy" in value:
        binding = value["baselineStudy"]
        require(
            isinstance(binding, dict)
            and binding.get("file") == "experiments\\bcal-full-gold\\study.json"
            and binding.get("sha256") == "1e9c638a70aa8a5e45deb3716dae5a48705910ade71f1dca3f6f24c221776f86",
            "Only the immutable original full-gold study may seed this repeat.",
        )
        baseline_path = ROOT / binding["file"]
        baseline_lf_bytes = baseline_path.read_bytes().replace(b"\r\n", b"\n")
        require(hashlib.sha256(baseline_lf_bytes).hexdigest() == binding["sha256"], "Original full-gold manifest changed.")
        baseline = json.loads(baseline_lf_bytes)
        legacy_only = value.get("studyId") == "bcal-full-gold-legacy-utf8-validation1"
        require(
            (
                (legacy_only and value.get("legacyValidationOf") == {"runId": 43494812835, "sourceSha": "de2014bb322d17c0503de1f3785a1bf1efb62151"})
                or (not legacy_only and value.get("studyId") == "bcal-full-gold-sol-paired-legacy-diagnostics-repeat1")
            )
            and value.get("repeatOf") == {"runId": 43422730966, "sourceSha": "be848023dea5412fd1f23cba4a5995b84270059f"}
            and set(value)
            <= {"schemaVersion", "studyId", "baselineStudy", "repeatOf", "relationship", "package", "runtimeEffortProof", "runtimeDiagnosticsProof", "historicalAccounting", "publication"}
            | ({"legacyValidationOf"} if legacy_only else set()),
            "Only the separately approved diagnostics repeat is admitted; selectors and scoring cannot be overridden.",
        )
        require(
            isinstance(value.get("package"), dict)
            and isinstance(value["package"].get("sha256"), str)
            and re.fullmatch("[0-9a-f]{64}", value["package"]["sha256"])
            and isinstance(value["package"].get("sourceCommitSha"), str)
            and re.fullmatch("[0-9a-f]{40}", value["package"]["sourceCommitSha"])
            and value["package"].get("sha256") != baseline["package"]["sha256"]
            and value["package"].get("sourceCommitSha") != baseline["package"]["sourceCommitSha"],
            "The repeat diagnostic runtime package has not been admitted.",
        )
        require(
            all(value["package"].get(key) == baseline["package"][key] for key in ("id", "nativeCatalogSha256", "sdkPackageVersion", "sdkRuntimeVersion", "framework")),
            "The diagnostic repeat must preserve the original native/catalog contract.",
        )
        require(isinstance(value.get("runtimeDiagnosticsProof"), dict), "Actual packaged diagnostic producer proof has not been admitted.")
        value = {**baseline, **value}
        if legacy_only:
            value.update(cohort="full-gold-legacy-v1", variants=["legacy"])
    return value


def study() -> dict:
    value = study_manifest()
    if value.get("cohort") in ("full-gold-paired-v1", "full-gold-legacy-v1"):
        require(
            value["repeatCount"] == 1
            and value["variants"] == (["legacy"] if value["cohort"] == "full-gold-legacy-v1" else ["legacy", "copilot-sdk"])
            and value["caseCount"] == 110
            and value["maxWorkers"] == 32
            and value["inference"]["model"] == "gpt-56-reasoning-sol"
            and value["inference"]["reasoning"] == "none"
            and value["judge"]["model"] == "gpt-56-ceres",
            "Only the approved full-gold paired Sol workload is admitted.",
        )
        require(digest(symbols_manifest()) == value["symbolsManifestSha256"], "Symbol manifest changed.")
        return value
    budget = value["budget"]
    prior = budget["preservedPriorHostedStudy"]
    corrected = budget["preservedCorrectedHostedStudy"]
    require(all(item["totalMeasuredSeconds"] == sum(item["fullJobSeconds"]) for item in (prior, corrected)), "Prior hosted job charges do not reconcile.")
    require(
        abs(budget["historicalMeasuredSeconds"] - budget["originalLocalMeasuredSeconds"] - prior["totalMeasuredSeconds"] - corrected["totalMeasuredSeconds"]) < 1e-6,
        "Prior hosted charges are missing from carry-forward.",
    )
    require(
        value["repeatCount"] == 1 and value["variants"] == ["legacy", "copilot-sdk"] and budget["pairCount"] == 8 and budget["maxWorkers"] == 4,
        "Only the approved eight one-repeat pairs are admitted.",
    )
    reserved = (
        budget["localNoModelAdmissionReservationSeconds"]
        + budget["preflightReservationSeconds"]
        + budget["controllerReservationSeconds"]
        + budget["pairCount"] * budget["pairReservationSeconds"]
        + budget["summaryReservationSeconds"]
    )
    if reserved > 28800 or budget["historicalMeasuredSeconds"] + budget["unresolvedLocalReservationSeconds"] + 28800 > budget["originalEnvelopeSeconds"]:
        raise ValueError("Aggregate budget does not fit the approved carry-forward envelope.")
    if digest(symbols_manifest()) != value["symbolsManifestSha256"]:
        raise ValueError("Symbol manifest changed.")
    return value


def pairs() -> list[dict]:
    result = []
    config = study()
    full_gold = config.get("cohort") in ("full-gold-paired-v1", "full-gold-legacy-v1")
    for dataset in config["datasets"]:
        path = ROOT / dataset["file"]
        if digest(path) != dataset["datasetSha256"]:
            raise ValueError("Dataset changed.")
        data = {row["instance_id"]: row for line in path.read_text(encoding="utf-8").splitlines() if line for row in [json.loads(line)]}
        if full_gold:
            require(
                dataset["category"] == "nl2al"
                and dataset["tier"] == "gold"
                and dataset["lane"] == "ordinary-quality"
                and len(data) == 110
                and set(data) == {item["instanceId"] for item in dataset["selectedEntries"]},
                "Full gold must select every case exactly once without exclusions.",
            )
        for selected in dataset["selectedEntries"]:
            row = data[selected["instanceId"]]
            if dataset["category"] == "nl2al":
                prompt = hashlib.sha256(row["nl_prompt"].encode()).hexdigest()
                expected = hashlib.sha256(json.dumps(row["expected"], sort_keys=True).encode()).hexdigest()
                require(prompt == selected["taskPromptSha256"] and expected == selected["expectedSha256"], "Entry prompt or assertions changed.")
                if full_gold:
                    require(
                        hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest() == selected["entrySha256"] and row["environment_setup_version"] == "28.0",
                        "Full-gold entry or symbol version changed.",
                    )
            else:
                require(dataset["category"] == "bcal-scenario" and row["metadata"]["area"] == "authority-contract", "Only repaired authority scenarios are admitted.")
                require(hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest() == selected["entrySha256"], "Authority fixture, seed, steps or assertions changed.")
                require(all(step["type"] == "user" for step in row["steps"]), "Native planning cannot reinterpret BCAL plan_action continuations.")
            order = ["legacy", "copilot-sdk"] if len(result) % 2 == 0 else ["copilot-sdk", "legacy"]
            if config["variants"] == ["legacy"]:
                order = ["legacy"]
            result.append(
                {
                    "index": len(result),
                    "category": dataset["category"],
                    "lane": dataset["lane"],
                    "tier": dataset["tier"],
                    "instanceId": row["instance_id"],
                    "repeat": 1,
                    "order": order,
                    "sdkToolCatalogSha256": selected["sdkToolCatalogSha256"] if dataset["lane"] == "authority" else study()["package"]["nativeCatalogSha256"],
                }
            )
    if full_gold:
        require(len(result) == 110 and all(pair["lane"] == "ordinary-quality" for pair in result), "Exactly110 full-gold pairs are required.")
    else:
        require(len(result) == 8 and sum(pair["lane"] == "authority" for pair in result) == 4, "Only four ordinary and four authority pairs are admitted.")
    require(len({pair["instanceId"] for pair in result}) == len(result), "Duplicate study selectors are not admitted.")
    return result


def fixtures(args: argparse.Namespace) -> None:
    from bcbench.agent.bcal.scenario import workspace_seed_evidence, write_execution_manifest
    from bcbench.dataset import BCalScenarioEntry
    from bcbench.evaluate.bcal_scenario import BCalScenarioPipeline

    receipts = {}
    for pair in pairs():
        if pair["lane"] != "authority":
            continue
        entry = BCalScenarioEntry.load(ROOT / "dataset" / "bcal_scenario.jsonl", entry_id=pair["instanceId"])[0]
        workspace = args.work / "fixtures" / str(pair["index"])
        BCalScenarioPipeline().setup_workspace(entry, workspace)
        write_execution_manifest(entry, workspace / "execution.json")
        seed = workspace_seed_evidence(workspace / "app")
        symbols = json.loads(symbols_manifest().read_bytes())["files"]
        require(
            {path.name: digest(path) for path in (workspace / ".bcal-symbols" / ".alpackages").glob("*.app")} == {Path(item["path"]).name: item["sha256"] for item in symbols},
            "Authority materialization did not use the exact350 symbols.",
        )
        require(seed.file_count == len(entry.workspace_files) + 3, "Unexpected authority seed/bootstrap file count.")
        manifest = json.loads((workspace / "execution.json").read_bytes())
        require(set(manifest) == {"schemaVersion", "session", "workspaceSeed", "steps", "interactions"}, "Hidden evaluation leaked into execution manifest.")
        require(manifest["schemaVersion"] == "1.1" and manifest["workspaceSeed"]["contractVersion"] == "1.0", "Scenario/seed contract differs.")
        receipts[pair["instanceId"]] = seed.model_dump(mode="json", by_alias=True)
    write_json(args.work / "fixtures.json", receipts)


def verify_symbols() -> dict:
    manifest = json.loads(symbols_manifest().read_bytes())
    root = Path(os.environ.get("BCAL_STUDY_SYMBOL_CACHE", r"C:\bcartifacts.cache\sandbox")) / manifest["cacheVersion"]
    expected = {item["path"]: item["sha256"] for item in manifest["files"]}
    observed = {str(path.relative_to(root)): digest(path) for path in root.rglob("*.app")}
    if len(expected) != 350 or expected != observed:
        raise ValueError("Expected the exact350 frozen symbols, not Latest.")
    roots = sorted(root.parent.glob("28.0.*"), key=lambda item: tuple(map(int, item.name.split("."))))
    if roots[-1] != root:
        raise ValueError("Pipeline would select a different28.0 symbol cache.")
    return {"count": 350, "setSha256": manifest["setSha256"], "manifestSha256": digest(symbols_manifest())}


def verify_package(stage: Path) -> Path:
    config = study()["package"]
    binary = stage / "tools" / "net10.0" / "any" / "bcal.exe"
    value = subprocess.check_output([str(binary), "--version"], text=True, timeout=30).strip()
    if value != config["productVersion"]:
        raise ValueError("Governed BCAL source/version mismatch.")
    dependencies = json.loads((binary.parent / "bcal.deps.json").read_bytes())
    if f"GitHub.Copilot.SDK/{config['sdkPackageVersion']}" not in dependencies["libraries"]:
        raise ValueError("Governed SDK dependency mismatch.")
    with zipfile.ZipFile(stage.parent / "package.nupkg") as archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        observed = {path.relative_to(stage).as_posix() for path in stage.rglob("*") if path.is_file()}
        require(observed == {item.filename for item in entries}, "Staged package inventory changed.")
        for item in entries:
            require(digest(stage / item.filename) == hashlib.sha256(archive.read(item)).hexdigest(), "Staged package bytes changed.")
        if installed := os.environ.get("BCAL_STUDY_INSTALLED_BINARY"):
            installed_binary = Path(installed)
            for path in binary.parent.rglob("*"):
                if path.is_file():
                    require(digest(installed_binary.parent / path.relative_to(binary.parent)) == digest(path), "Installed action payload differs from the sealed package.")
            binary = installed_binary
    return binary


def prepare_package(folder: Path) -> dict:
    config = study()["package"]
    folder.mkdir(parents=True, exist_ok=True)
    package = folder / "package.nupkg"
    if not package.exists():
        installed = Path(os.environ["BCAL_STUDY_INSTALLED_BINARY"])
        filename = f"{config['id'].lower()}.{config['version']}.nupkg"
        candidates = [parent / filename for parent in installed.parents[:5]]
        candidates.append(Path.home() / ".nuget" / "packages" / config["id"].lower() / config["version"] / filename)
        archives = [path for path in candidates if path.is_file()]
        require(bool(archives), "Existing install action did not retain the exact package archive.")
        require(all(path.stat().st_size == config["bytes"] and digest(path) == config["sha256"] for path in archives), "Installed action archive bytes differ.")
        shutil.copyfile(archives[0], package)
    if package.stat().st_size != config["bytes"] or digest(package) != config["sha256"]:
        raise ValueError("New or corrupt package bytes are not admitted.")
    stage = folder / "stage"
    if not stage.exists():
        with zipfile.ZipFile(package) as archive:
            files = [entry for entry in archive.infolist() if not entry.is_dir()]
            if len(files) != config["files"] or any(not (stage / entry.filename).resolve().is_relative_to(stage.resolve()) for entry in files):
                raise ValueError("Unexpected governed archive inventory.")
            archive.extractall(stage)
    binary = verify_package(stage)
    return {"sha256": config["sha256"], "sourceCommitSha": config["sourceCommitSha"], "framework": "net10.0", "versionVerified": True, "binarySha256": digest(binary)}


def verify_runtime_effort_proof() -> dict[str, str] | None:
    config = study()
    if config.get("cohort") not in ("full-gold-paired-v1", "full-gold-legacy-v1"):
        return None
    binding = config.get("runtimeEffortProof")
    if binding is None:
        raise ValueError("Actual governed package SDK effort proof has not been admitted.")
    if not isinstance(binding, dict):
        raise TypeError("Runtime effort proof binding must be an object.")
    filename, checksum = binding.get("file"), binding.get("sha256")
    if not isinstance(filename, str) or not isinstance(checksum, str):
        raise TypeError("Runtime effort proof binding is malformed.")
    path = (ROOT / filename).resolve()
    require(path.is_relative_to(ROOT) and digest(path) == checksum, "Runtime effort proof binding differs.")
    proof = json.loads(path.read_bytes())
    if config["variants"] == ["legacy"]:
        require(
            proof.get("status") == "passed"
            and proof.get("packageSha256") == config["package"]["sha256"]
            and proof.get("packageSourceCommitSha") == config["package"]["sourceCommitSha"]
            and proof.get("legacyBridgeVerified") is True
            and proof.get("observedLegacyWireEffort") == config["inference"]["reasoning"]
            and proof.get("utf8SubprocessVerified") is True
            and proof.get("providerRequests") == proof.get("networkRequests") == 0,
            "Actual fixed legacy bridge effort/output proof has not passed.",
        )
        verify_proof_sources(proof)
        return {"file": filename, "sha256": checksum}
    require(
        proof.get("status") == "passed"
        and proof.get("packageSha256") == config["package"]["sha256"]
        and proof.get("packageSourceCommitSha") == config["package"]["sourceCommitSha"]
        and proof.get("requestedSdkEffort") == proof.get("observedSdkWireEffort") == config["inference"]["reasoning"]
        and proof.get("nativeSdkInvoked") is True
        and proof.get("mismatchRejectedBeforeProvider") is True
        and proof.get("legacyBridgeVerified") is True,
        "Actual package SDK/legacy effort fidelity has not been verified.",
    )
    return {"file": filename, "sha256": checksum}


def verify_proof_sources(proof: dict) -> None:
    expected = {"scripts\\bcal_governed_study.py", "scripts\\bcal_study_transport.py", "src\\bcbench\\agent\\bcal\\bc_eval_sdk_proxy.py"}
    sources = proof.get("sourceHashes")
    require(isinstance(sources, dict) and set(sources) == expected, "Exact legacy proof source inventory is missing.")
    for filename, checksum in sources.items():
        canonical = subprocess.check_output(["git", "show", f"HEAD:{filename.replace(chr(92), '/')}"], cwd=ROOT)
        require(hashlib.sha256(canonical).hexdigest() == checksum, "Fixed legacy proof source changed.")
        require((ROOT / filename).read_bytes().replace(b"\r\n", b"\n") == canonical, "Fixed legacy checkout content changed.")


def verify_runtime_diagnostics_proof() -> dict[str, str] | None:
    config = study()
    if "repeatOf" not in config:
        return None
    binding = config["runtimeDiagnosticsProof"]
    filename, checksum = binding.get("file"), binding.get("sha256")
    require(isinstance(filename, str) and isinstance(checksum, str), "Runtime diagnostics proof binding is malformed.")
    path = (ROOT / filename).resolve()
    require(path.is_relative_to(ROOT) and digest(path) == checksum, "Runtime diagnostics proof binding differs.")
    proof = json.loads(path.read_bytes())
    if config["variants"] == ["legacy"]:
        verify_proof_sources(proof)
    require(
        proof.get("status") == "passed"
        and proof.get("packageSha256") == config["package"]["sha256"]
        and proof.get("packageSourceCommitSha") == config["package"]["sourceCommitSha"]
        and proof.get("commandClientInvoked") is True
        and proof.get("invocationCollectorInvoked") is True
        and type(proof.get("providerRequests")) is int
        and proof["providerRequests"] == 0
        and proof.get("consumerProjectionVerified") is True,
        "Actual packaged producer and safe Bench consumer have not both been verified.",
    )
    events = proof.get("observedModelInterruptions")
    require(
        isinstance(events, list)
        and all(
            isinstance(event, dict)
            and event.get("type") == "model_interrupted"
            and isinstance(event.get("modelFailure"), dict)
            and set(event["modelFailure"]) <= {"stage", "exceptionCategory", "exitCode"}
            and isinstance(event["modelFailure"].get("exceptionCategory"), str)
            and event["modelFailure"]["exceptionCategory"] in MODEL_FAILURE_CATEGORIES
            and isinstance(event["modelFailure"].get("stage"), str)
            and event["modelFailure"]["stage"] in MODEL_FAILURE_STAGES
            and (event["modelFailure"].get("exitCode") is None or (type(event["modelFailure"]["exitCode"]) is int and -(2**31) <= event["modelFailure"]["exitCode"] < 2**31))
            for event in events
        )
        and {event["modelFailure"]["stage"] for event in events} >= {"command_start", "command_io", "command_exit", "response_json", "response_choices", "response_message"},
        "Runtime diagnostics proof does not cover the required command and response boundaries.",
    )
    return {"file": filename, "sha256": checksum}


def preflight(args: argparse.Namespace) -> None:
    receipt = {
        "schemaVersion": "1",
        "studyId": study()["studyId"],
        "benchCommit": os.environ.get("GITHUB_SHA"),
        "inputsSha256": digest(INPUTS / "study.json"),
        "kind": "no-model-hosted-preflight",
        "modelsAdmitted": 0,
        "status": "in-progress",
    }
    write_json(args.output / "preflight.json", receipt)
    started = time.monotonic()
    try:
        receipt["runtimeDiagnosticsProof"] = verify_runtime_diagnostics_proof()
        receipt["runtimeEffortProof"] = verify_runtime_effort_proof()
        receipt["package"] = prepare_package(args.work / "package")
        receipt["symbols"] = verify_symbols()
        receipt["pairCount"] = len(pairs())
        receipt["authoritySeeds"] = json.loads((args.work / "fixtures.json").read_bytes())
        expected_seeds = sum(pair["lane"] == "authority" for pair in pairs())
        require(len(receipt["authoritySeeds"]) == expected_seeds, "Authority materializations differ from the selected workload.")
        from azure.identity import CertificateCredential
        from bc_eval.llm.llm_api import SCOPE, LlmApiSettings

        settings = LlmApiSettings.from_env()
        with CertificateCredential(settings.tenant_id, settings.client_id, certificate_path=os.environ["LLM_API_CERTIFICATE_FILE"], send_certificate_chain=True) as credential:
            token = credential.get_token(SCOPE)
            require(token.expires_on > time.time(), "Expired provider token.")
        receipt["certificateTokenAcquired"] = True
        receipt["status"] = "passed"
    except Exception as error:
        receipt.update(status="failed", errorClass=type(error).__name__)
        raise
    finally:
        receipt["seconds"] = time.monotonic() - started
        write_json(args.output / "preflight.json", receipt)


@contextmanager
def proxy(work: Path, env: dict[str, str], model: str, wire: str, step: str, *, explicit_none_probe: bool = False) -> Iterator[tuple[str, Path]]:
    ready, audit = work / f"{step}-{wire}.ready.json", work / f"{step}-{wire}.audit.json"
    command = [
        os.environ["BCAL_STUDY_INFERENCE_PYTHON"],
        str(ROOT / "scripts" / "bcal_study_transport.py"),
        "serve",
        "--model",
        model,
        "--wire-api",
        wire,
        "--step",
        step,
        "--ready",
        str(ready),
        "--audit",
        str(audit),
    ]
    if explicit_none_probe:
        command.append("--explicit-none-probe")
    if step == "HostAgent" and study()["inference"]["reasoning"] == "none":
        command.extend(["--required-reasoning-effort", "none"])
    with (work / f"{step}-{wire}.console.txt").open("w", encoding="utf-8") as console:
        process = subprocess.Popen(command, env=env, stdout=console, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 40
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.2)
            if process.poll() is not None or not ready.exists():
                raise RuntimeError("Owned inference proxy failed readiness.")
            url = json.loads(ready.read_bytes())["base_url"]
            request = urllib.request.Request(url + "/health", headers={"Authorization": "Bearer " + env["BCAL_SDK_PROXY_KEY"]})
            with urllib.request.urlopen(request, timeout=5) as response:
                if json.load(response) != {"status": "ready", "wireApi": wire, "model": model}:
                    raise ValueError("Proxy model/protocol changed.")
            yield url, audit
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def route_receipt(path: Path, *, explicit_none_probe: bool = False, required_reasoning_effort: str | None = None) -> dict:
    value = json.loads(path.read_bytes())
    expected = {"requests", "http200", "ticketsReturned", "ticketsReplayed", "sessionStable", "modelStable"}
    if explicit_none_probe:
        expected.add("explicitNoneVerifiedRequests")
    if required_reasoning_effort:
        expected.update(("reasoningEffort", "effortVerifiedRequests", "effortRejectedRequests"))
    if set(value) != expected:
        raise ValueError("Unexpected route receipt.")
    if (
        any(type(value[key]) is not int or value[key] < 0 for key in ("requests", "http200", "ticketsReturned", "ticketsReplayed"))
        or value["sessionStable"] is not True
        or value["modelStable"] is not True
    ):
        raise ValueError("Invalid route counters.")
    if explicit_none_probe and (type(value["explicitNoneVerifiedRequests"]) is not int or value["explicitNoneVerifiedRequests"] != value["requests"]):
        raise ValueError("Explicit-none outbound effort was not verified.")
    if required_reasoning_effort and (
        value["reasoningEffort"] != required_reasoning_effort
        or type(value["effortVerifiedRequests"]) is not int
        or value["effortVerifiedRequests"] != value["requests"]
        or type(value["effortRejectedRequests"]) is not int
        or value["effortRejectedRequests"] != 0
    ):
        raise ValueError("Governed outbound reasoning effort was not verified.")
    if value["requests"] > 1 and value["http200"] and not value["ticketsReplayed"]:
        raise ValueError("No cross-turn sticky route proof.")
    return value


def route_failure_diagnostics(path: Path) -> dict[str, object]:
    result: dict[str, object] = {"verified": False, "auditSha256": digest(path)}
    try:
        value = json.loads(path.read_bytes())
    except json.JSONDecodeError:
        return {**result, "counterEvidenceAvailable": False, "errorClass": "JSONDecodeError"}
    if not isinstance(value, dict):
        return {**result, "counterEvidenceAvailable": False, "errorClass": "InvalidCounterObject"}
    counters = {
        key: value[key] for key in ("requests", "http200", "ticketsReturned", "ticketsReplayed", "effortVerifiedRequests", "effortRejectedRequests") if type(value.get(key)) is int and value[key] >= 0
    }
    return {**result, "counterEvidenceAvailable": {"requests", "http200"} <= counters.keys(), "counters": counters}


def legacy_diagnostic_receipt(path: Path) -> dict:
    if not path.exists():
        return {"available": False, "events": None}
    try:
        raw = path.read_bytes()
    except OSError:
        return {"available": True, "valid": False, "errorCategory": "io", "events": None}
    result = {"available": True, "sourceSha256": hashlib.sha256(raw).hexdigest(), "valid": False, "events": None}
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        return result
    if not isinstance(value, dict) or value.get("schemaVersion") != 1 or not isinstance(value.get("events"), list):
        return result
    allowed = {
        "phase": {"command", "input", "client", "response", "serialization", "output", "request", "headers", "body", "guard"},
        "outcome": {"started", "failed", "received", "completed", "emitted", "invalid_json", "invalid_object", "missing_choices", "empty_choices", "missing_message", "message_present"},
        "category": {
            "unknown",
            "timeout",
            "transport",
            "json_decode",
            "body_decode",
            "unicode_encode",
            "http_status",
            "response_validation",
            "model_mismatch",
            "effort_mismatch",
            "command_io",
            "client_disconnect",
        },
    }
    events = []
    for event in value["events"]:
        if not isinstance(event, dict) or not {"phase", "outcome"} <= event.keys():
            return result
        safe = {key: event[key] if isinstance(event.get(key), str) and event[key] in choices else None for key, choices in allowed.items() if key in event}
        for key in ("httpStatus", "requestsObserved"):
            if key in event:
                number = event[key]
                safe[key] = number if type(number) is int and (100 <= number <= 599 if key == "httpStatus" else number >= 0) else None
        if "observedAtUtc" in event:
            try:
                timestamp = datetime.fromisoformat(event["observedAtUtc"])
                safe["observedAtUtc"] = timestamp.astimezone(UTC).isoformat() if timestamp.tzinfo is not None else None
            except (TypeError, ValueError):
                safe["observedAtUtc"] = None
        events.append(safe)
    return {**result, "valid": True, "events": events}


def provider_failure(error: urllib.error.HTTPError) -> dict:
    raw = error.read(65536)
    text = raw.decode("utf-8", errors="replace").lower()
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError):
        body = {}
    detail = body.get("error", {}) if isinstance(body, dict) else {}
    if not isinstance(detail, dict):
        detail = {}
    parameter = detail.get("param")
    allowed_parameters = {
        "model",
        "tools",
        "tool_choice",
        "max_completion_tokens",
        "max_output_tokens",
        "max_tokens",
        "reasoning_effort",
        "stream",
        "messages",
        "input",
        "response_format",
        "temperature",
        "top_p",
    }
    return {
        "httpStatus": error.code,
        "responseBodySha256": hashlib.sha256(raw).hexdigest(),
        "parameter": parameter if isinstance(parameter, str) and parameter in allowed_parameters else None,
        "providerCodeSha256": hashlib.sha256(str(detail.get("code")).encode()).hexdigest() if detail.get("code") is not None else None,
        "signals": {
            "mentionsReasoningEffort": "reasoning_effort" in text,
            "mentionsTools": "tool" in text,
            "mentionsToolChoice": "tool_choice" in text,
            "mentionsCompletionTokenLimit": "max_completion_tokens" in text or "max_output_tokens" in text,
            "unsupportedParameter": "unsupported parameter" in text or "unsupported_parameter" in text,
            "unsupportedValue": "unsupported value" in text or "unsupported_value" in text,
            "modelUnavailable": "model_not_found" in text or "deploymentnotfound" in text or "model not found" in text,
            "permissionDenied": "permission_denied" in text or "unauthorized" in text or "access denied" in text,
            "invalidSchema": "invalid schema" in text or "invalid_function_parameters" in text,
        },
    }


def routing_preflight(args: argparse.Namespace, *, explicit_none_probe: bool = False) -> None:
    config = study()
    require(config.get("cohort") in ("full-gold-paired-v1", "full-gold-legacy-v1"), "Routing admission is only configured for full gold.")
    require(not explicit_none_probe or config["variants"] != ["legacy"], "The legacy-only lane does not admit Responses probes.")
    if "repeatOf" in config:
        require(not explicit_none_probe, "Extra explicit-none probes are not authorized for the diagnostic repeat.")
        verify_runtime_diagnostics_proof()
        verify_runtime_effort_proof()
    legacy_only = study()["variants"] == ["legacy"]
    receipt = {
        "studyId": config["studyId"],
        "benchCommit": os.environ.get("GITHUB_SHA"),
        "inputsSha256": digest(INPUTS / "study.json"),
        "status": "in-progress",
        "kind": "explicit-none-protocol-probes-not-gold-admission" if explicit_none_probe else "bounded-routing-admission-not-semantic-attempts",
        "requestLimit": 2 if explicit_none_probe else 3 if legacy_only else 5,
        "reasoningEffort": "none" if explicit_none_probe else config["inference"]["reasoning"],
        "routes": [],
    }
    if explicit_none_probe:
        receipt.update(semanticAttempts=0, goldAdmission=False, sdkExecution=False, stickyReplayProven=False)
    started = time.monotonic()
    env = {**os.environ, "BCAL_SDK_PROXY_KEY": secrets.token_urlsafe(32)}
    if legacy_only:
        env["BCAL_AGENT_RUNTIME"] = "legacy"
    try:
        routes = (
            (config["inference"]["model"], "chat-completions", "HostAgent", 2),
            (config["inference"]["model"], "responses", "HostAgent", 2),
            (config["judge"]["model"], "chat-completions", "Judge", 1),
        )
        if explicit_none_probe:
            routes = tuple((model, wire, role, 1) for model, wire, role, _ in routes[:2])
        elif legacy_only:
            routes = (routes[0], routes[2])
        for model, wire, role, count in routes:
            route_receipt_row = {"model": model, "wireApi": wire, "role": role, "requests": 0}
            receipt["routes"].append(route_receipt_row)
            probe_options = {"explicit_none_probe": True} if explicit_none_probe else {}
            required_effort = config["inference"]["reasoning"] if role == "HostAgent" else None
            with proxy(args.work, env, model, wire, role, **probe_options) as (url, audit):
                try:
                    for _ in range(count):
                        body = {"model": model}
                        function = {
                            "name": "admission_probe",
                            "description": "Unused schema admission only.",
                            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                        }
                        if wire == "responses":
                            body.update(input="Return only OK.", max_output_tokens=1024, tools=[{"type": "function", **function}], tool_choice="none")
                            route = "/responses"
                        else:
                            body.update(messages=[{"role": "user", "content": "Return only OK."}], max_completion_tokens=16384, tools=[{"type": "function", "function": function}])
                            route = "/chat/completions"
                        if explicit_none_probe or required_effort:
                            if wire == "responses":
                                body.pop("tool_choice")
                                body.update(input=[{"role": "user", "content": "Return only OK."}], reasoning={"effort": "none"}, parallel_tool_calls=False)
                            else:
                                body["reasoning_effort"] = "none"
                            route_receipt_row["requestShape"] = {
                                "keys": sorted(body),
                                "toolCount": len(body["tools"]),
                                "reasoningEffort": "none",
                                "maxCompletionTokens": body.get("max_completion_tokens"),
                                "maxOutputTokens": body.get("max_output_tokens"),
                            }
                        if legacy_only and role == "HostAgent":
                            diagnostics = args.work / "admission-bridge-diagnostics"
                            diagnostics.mkdir(exist_ok=True)
                            command_env = {**env, "BCAL_LLM_MODEL": model, "BCAL_STUDY_CHAT_URL": url, "BCAL_STUDY_REASONING_EFFORT": "none", "BCAL_STUDY_BRIDGE_DIAGNOSTICS": str(diagnostics)}
                            response = subprocess.run(
                                [os.environ["BCAL_STUDY_INFERENCE_PYTHON"], str(ROOT / "scripts" / "bcal_study_transport.py"), "bridge"],
                                input=json.dumps(body).encode("utf-8"),
                                capture_output=True,
                                check=True,
                                timeout=250,
                                env=command_env,
                            )
                            result = json.loads(response.stdout.decode("utf-8"))
                        else:
                            request = urllib.request.Request(
                                url + route,
                                data=json.dumps(body).encode(),
                                headers={"Authorization": "Bearer " + env["BCAL_SDK_PROXY_KEY"], "Content-Type": "application/json"},
                            )
                            try:
                                with urllib.request.urlopen(request, timeout=250) as response:
                                    result = json.load(response)
                            except urllib.error.HTTPError as error:
                                route_receipt_row["failure"] = provider_failure(error)
                                raise
                        require(
                            isinstance(result, dict) and (isinstance(result.get("output"), list) if wire == "responses" else isinstance(result.get("choices"), list)),
                            "Provider response protocol differs.",
                        )
                        if explicit_none_probe or required_effort or role == "Judge":
                            if wire == "responses":
                                require(
                                    result.get("status") == "completed" and not result.get("error") and any(item.get("type") in {"message", "function_call"} for item in result["output"]),
                                    "Responses probe did not complete.",
                                )
                            else:
                                require(
                                    bool(result["choices"])
                                    and all(
                                        choice.get("finish_reason") in {"stop", "tool_calls"}
                                        and isinstance(choice.get("message"), dict)
                                        and (choice["message"].get("content") or choice["message"].get("tool_calls"))
                                        for choice in result["choices"]
                                    ),
                                    "Chat probe did not complete.",
                                )
                            route_receipt_row["responseProtocolValid"] = True
                            usage = result.get("usage")
                            route_receipt_row["usage"] = (
                                {
                                    key: value
                                    for key, value in usage.items()
                                    if key in {"input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens"} and type(value) is int and value >= 0
                                }
                                if isinstance(usage, dict)
                                else None
                            )
                finally:
                    counters = json.loads(audit.read_bytes())
                    if type(counters.get("requests")) is int and counters["requests"] >= 0:
                        route_receipt_row["requests"] = counters["requests"]
                    try:
                        route_receipt_row.update(route_receipt(audit, required_reasoning_effort=required_effort, **probe_options))
                    except ValueError:
                        route_receipt_row["routeFailure"] = route_failure_diagnostics(audit)
                        raise
                require(route_receipt_row["requests"] == count and route_receipt_row["http200"] == count, "Routing admission was not exactly the bounded successful calls.")
                if legacy_only and role == "HostAgent":
                    projected = [legacy_diagnostic_receipt(path) for path in sorted(diagnostics.glob("bridge-*.json"))]
                    require(
                        len(projected) == 2 and all(item.get("valid") is True and item["events"][-1]["outcome"] == "emitted" for item in projected), "Actual legacy admission bridge evidence missing."
                    )
                    route_receipt_row["bridgeInvocations"] = projected
        receipt["status"] = "passed"
    except Exception as error:
        receipt.update(status="failed", errorClass=type(error).__name__)
        raise
    finally:
        receipt["seconds"] = time.monotonic() - started
        receipt["requests"] = sum(row["requests"] for row in receipt["routes"])
        write_json(args.output / ("explicit-none-probe.json" if explicit_none_probe else "routing-preflight.json"), receipt)


def trace_projection(transcript: dict) -> dict:
    trace = transcript.get("evidence", {}).get("trace") or {}
    raw_events = trace.get("events")
    complete = (
        trace.get("truncated") is False
        and type(trace.get("omittedEventCount")) is int
        and trace["omittedEventCount"] == 0
        and isinstance(raw_events, list)
        and all(isinstance(item, dict) for item in raw_events)
    )
    types = {
        "compilation_attempt",
        "compilation_outcome",
        "completion_assessment_outcome",
        "completion_assessment_start",
        "deployment_transition",
        "model_request",
        "model_response",
        "plan_lifecycle_transition",
        "tool_completed",
        "tool_started",
        "native_completion_intent",
        "native_plan_approval",
        "model_interrupted",
        "turn_interrupted",
    }
    events = []
    for event in raw_events if isinstance(raw_events, list) else []:
        if not isinstance(event, dict):
            continue
        safe = {key: event[key] for key in ("sequence", "turn", "iteration", "inputLength", "requestedToolCallCount", "succeeded") if type(event.get(key)) in (int, bool)}
        safe["type"] = event["type"] if event.get("type") in types else "other-event"
        for key in ("toolName", "operation", "inputHash", "callId", "compositionId", "fromState", "toState", "status"):
            if isinstance(event.get(key), str):
                safe[key + "Sha256"] = hashlib.sha256(event[key].encode()).hexdigest()
        if isinstance(event.get("scenarioStepId"), str):
            safe["scenarioStepIdSha256"] = hashlib.sha256(event["scenarioStepId"].encode()).hexdigest()
        if event.get("type") == "native_plan_approval" and event.get("status") in {"approved", "not_approved"}:
            safe["status"] = event["status"]
        if event.get("type") in {"model_interrupted", "turn_interrupted"}:
            for key, allowed in (
                ("operation", {"delivery", "turn"}),
                ("status", {"interrupted", "failed", "canceled"}),
                ("interruptionReason", {"failed", "canceled"}),
            ):
                safe[key] = event[key] if isinstance(event.get(key), str) and event[key] in allowed else None
        if event.get("type") == "model_interrupted":
            if type(event.get("promptUseSequence")) is int:
                safe["promptUseSequence"] = event["promptUseSequence"]
            failure = event.get("modelFailure")
            if isinstance(failure, dict):
                safe["modelFailure"] = {
                    "stage": failure["stage"] if isinstance(failure.get("stage"), str) and failure["stage"] in MODEL_FAILURE_STAGES else None,
                    "exceptionCategory": failure["exceptionCategory"] if isinstance(failure.get("exceptionCategory"), str) and failure["exceptionCategory"] in MODEL_FAILURE_CATEGORIES else None,
                    "exitCode": failure["exitCode"] if type(failure.get("exitCode")) is int and -(2**31) <= failure["exitCode"] < 2**31 else None,
                }
            else:
                safe["modelFailure"] = None
        events.append(safe)
    return {
        "complete": complete,
        "truncated": trace.get("truncated") if type(trace.get("truncated")) is bool else None,
        "omittedEventCount": trace.get("omittedEventCount") if type(trace.get("omittedEventCount")) is int else None,
        "events": events,
        "contentProjection": "numeric-hash-and-allowlisted-enums",
        "originalTraceSha256": hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest(),
    }


def verify_owned_cleanup(binary: Path) -> None:
    if os.name == "nt":
        env = {**os.environ, "BCAL_STUDY_PROCESS_ROOT": str(binary.parent) + os.sep}
        script = "@(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($env:BCAL_STUDY_PROCESS_ROOT, [StringComparison]::OrdinalIgnoreCase) }).Count"
        count = subprocess.check_output(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env, text=True, timeout=15).strip()
        require(count == "0", "An owned packaged runtime process remains; stop admissions.")


def model_response_observed(route: dict, transcript: dict) -> bool:
    if route["http200"] == 0:
        return False
    native = any(type(turn.get("modelRequests")) is int and turn["modelRequests"] > 0 for turn in transcript.get("agentRuntimeEvidence", []))
    legacy = any(event.get("type") == "model_response" for event in transcript.get("evidence", {}).get("trace", {}).get("events", []))
    return native or legacy


def sanitize_row(row: dict, runtime: str, *, sdk_catalog_sha256: str | None = None) -> dict:
    from bcbench.agent.bcal.agent import BCalBackendConfig, _require_completed, _result_metrics
    from bcbench.types import BCalAgentPlanning, BCalAgentRuntime

    transcript = row["transcript"]
    identity = transcript["runtimeIdentity"]
    model = study()["inference"]["model"]
    config = BCalBackendConfig(
        command="governed-memory-only-chat-route",
        model=model,
        agent_runtime=BCalAgentRuntime(runtime),
        agent_planning=BCalAgentPlanning.COPILOT if runtime == "copilot-sdk" else None,
        sdk_provider="openai" if runtime == "copilot-sdk" else None,
        sdk_model=model if runtime == "copilot-sdk" else None,
        sdk_reasoning_effort=study()["inference"]["reasoning"] if runtime == "copilot-sdk" else None,
        sdk_max_model_requests=64 if runtime == "copilot-sdk" else None,
        sdk_timeout_seconds=1200 if runtime == "copilot-sdk" else None,
        inference_provider="bc-eval-m365-test@0.6.1",
        llm_provider="bc-eval-m365-test@0.6.1",
        llm_wire_api="chat-completions",
    )
    expected = config.planning_identity()
    if identity.get("agentRuntime") != runtime or any(key not in identity or identity[key] != value for key, value in expected.items()):
        raise ValueError("Observed planning policy mismatch.")
    source = transcript.get("executionIdentity", {}).get("sourceCommitSha")
    if source != study()["package"]["sourceCommitSha"]:
        raise ValueError("Observed package source mismatch.")
    safe = {"policy": expected, "completed": False, "freshCompiled": None, "exported": False, "usage": {}, "identityHashes": {}}
    metrics = _result_metrics(transcript, 0)
    safe["usage"] = {"promptTokens": metrics.prompt_tokens, "completionTokens": metrics.completion_tokens, "totalTokens": metrics.total_tokens, "cost": None}
    if row.get("error_message") and safe["usage"]["totalTokens"] == 0:
        safe["usage"] = {"promptTokens": None, "completionTokens": None, "totalTokens": None, "cost": None}
    safe["toolUsageByNameHash"] = {hashlib.sha256(key.encode()).hexdigest(): value for key, value in (metrics.tool_usage or {}).items()}
    safe["canonicalTrace"] = trace_projection(transcript)
    for key in ("systemPromptSha256", "toolCatalogSha256"):
        value = identity.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("Missing or invalid prompt/catalog hash.")
        safe["identityHashes"][key] = value
    if runtime == "copilot-sdk":
        require((identity.get("sdkPackageVersion"), identity.get("sdkRuntimeVersion")) == ("1.0.29", "1.0.107"), "Observed SDK identity mismatch.")
        expected_catalog = sdk_catalog_sha256 or study()["package"]["nativeCatalogSha256"]
        require(identity["toolCatalogSha256"] == expected_catalog, "Observed context-specific SDK/catalog identity mismatch.")
    evidence = transcript.get("agentRuntimeEvidence") or []
    if evidence:
        final = evidence[-1]
        safe["freshCompiled"] = final.get("compileCoversLatestChange") if type(final.get("compileCoversLatestChange")) is bool else None
    if not row.get("error_message") and row.get("timeout") is not True:
        _require_completed(transcript, metrics=metrics, config=config.experiment(1500, transcript))
        safe["completed"] = True
        safe["exported"] = transcript.get("export", {}).get("success") is True
    safe["timeout"] = row.get("timeout") is True
    failures = [transcript.get("failure"), *(step.get("failure") for step in transcript.get("steps", []))]
    safe["failureCodeHashes"] = [hashlib.sha256(failure["code"].encode()).hexdigest() for failure in failures if isinstance(failure, dict) and isinstance(failure.get("code"), str)]
    safe["errorMessageSha256"] = hashlib.sha256(row["error_message"].encode()).hexdigest() if isinstance(row.get("error_message"), str) else None
    return safe


def authority_projection(row: dict, pair: dict) -> dict:
    from bcbench.dataset import BCalScenarioEntry

    entry = BCalScenarioEntry.load(ROOT / "dataset" / "bcal_scenario.jsonl", entry_id=pair["instanceId"])[0]
    transcript = row.get("transcript") or {}
    expected = {assertion.id for assertion in [*entry.evaluation.trace_assertions, *entry.evaluation.deterministic_artifact_assertions]}
    assertions = row.get("trace_assertions") or []
    require(all(item.get("assertion_id") in expected and type(item.get("passed")) is bool for item in assertions), "Unexpected authority assertion shape.")
    observed = {item["assertion_id"]: item["passed"] for item in assertions}
    require(len(observed) == len(assertions), "Duplicate authority assertions.")
    seeds = json.loads((Path(os.environ["BCAL_STUDY_WORK"]) / "fixtures.json").read_bytes())
    seed = transcript.get("workspaceSeed")
    seed_verified = seed == seeds[entry.instance_id]
    prompt = transcript.get("evidence", {}).get("promptEvidence") or {}
    prompt_complete = bool(prompt.get("compositions") and prompt.get("uses"))
    trace = transcript.get("evidence", {}).get("trace") or {}
    complete_trace = trace.get("truncated") is False and type(trace.get("omittedEventCount")) is int and trace["omittedEventCount"] == 0 and isinstance(trace.get("events"), list)
    return {
        "scenarioCompleted": row.get("scenario_completed") is True,
        "harnessFailure": row.get("harness_failure") is True,
        "independentBuildStatus": row.get("independent_build", {}).get("status") if row.get("independent_build", {}).get("status") in ("passed", "failed", "not_attempted") else None,
        "seedVerified": seed_verified,
        "seedAggregateSha256": seed.get("aggregateSha256") if seed_verified else None,
        "promptEvidenceComplete": prompt_complete,
        "canonicalTraceComplete": complete_trace,
        "independentBuildRequired": entry.evaluation.compile_required,
        "assertionsComplete": set(observed) == expected,
        "assertions": [{"assertionId": name, "passed": observed.get(name)} for name in sorted(expected)],
        "deterministicCompliant": set(observed) == expected
        and all(observed.values())
        and seed_verified
        and prompt_complete
        and complete_trace
        and row.get("scenario_completed") is True
        and (not entry.evaluation.compile_required or row.get("independent_build", {}).get("status") == "passed"),
    }


def run_attempt(pair: dict, runtime: str, work: Path, env: dict[str, str], public: Path) -> dict:
    from bcbench_core.exceptions import AgentError

    from bcbench.agent.bcal.agent import _run_bcal_process

    config = study()
    require(runtime in config["variants"], "Runtime is outside the admitted study.")
    work.mkdir(parents=True)
    attempt = {
        **{key: pair[key] for key in ("index", "category", "lane", "tier", "instanceId", "repeat")},
        "studyId": config["studyId"],
        "inputsSha256": digest(INPUTS / "study.json"),
        "benchCommit": os.environ.get("GITHUB_SHA"),
        "runtime": runtime,
        "mainModel": config["inference"]["model"],
        "reasoningEffort": config["inference"]["reasoning"],
        "runtimeRequestedReasoningEffort": config["inference"]["reasoning"] if runtime == "copilot-sdk" else None,
        "effortApplication": ("sdk-option-and-wire-guard" if runtime == "copilot-sdk" else "governed-command-bridge-and-wire-guard") if config["inference"]["reasoning"] is not None else None,
        "judgeModel": config["judge"]["model"],
        "status": "admitted",
        "quality": None,
        "testPassed": None,
        "firstModelResponse": False,
        "startedAtUtc": datetime.now(UTC).isoformat(),
    }
    write_json(public, attempt)
    started = time.monotonic()
    try:
        binary = verify_package(Path(os.environ["BCAL_STUDY_WORK"]) / "package" / "stage")
        unrelated_credentials = {"GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "STUDY_CERT_VAULT", "STUDY_CERT_NAME"}
        env = {key: value for key, value in env.items() if not key.startswith(("BCAL_", "VSS_")) and key not in unrelated_credentials}
        env.update(
            PATH=str(binary.parent) + os.pathsep + os.environ["PATH"],
            BCAL_AGENT_RUNTIME=runtime,
            BCAL_LLM_MODEL=config["inference"]["model"],
            BCAL_LLM_PROVIDER="bc-eval-m365-test@0.6.1",
            BCAL_LLM_WIRE_API="chat-completions",
            BCAL_INFERENCE_PROVIDER="bc-eval-m365-test@0.6.1",
            BCAL_SDK_PROXY_KEY=secrets.token_urlsafe(32),
            BCAL_LLM_COMMAND=subprocess.list2cmdline([os.environ["BCAL_STUDY_INFERENCE_PYTHON"], str(ROOT / "scripts" / "bcal_study_transport.py"), "bridge"]),
        )
        required_effort = config["inference"]["reasoning"]
        if runtime == "legacy":
            bridge_diagnostics = work / "bridge-diagnostics"
            bridge_diagnostics.mkdir()
            env["BCAL_STUDY_BRIDGE_DIAGNOSTICS"] = str(bridge_diagnostics)
        if required_effort is not None:
            env["BCAL_STUDY_REASONING_EFFORT"] = required_effort
        with ExitStack() as stack:
            chat_url, chat_audit = stack.enter_context(proxy(work, env, config["inference"]["model"], "chat-completions", "HostAgent"))
            env["BCAL_STUDY_CHAT_URL"] = chat_url
            main_audit = chat_audit
            if runtime == "copilot-sdk":
                sdk_url, main_audit = stack.enter_context(proxy(work, env, config["inference"]["model"], "responses", "HostAgent"))
                env.update(
                    BCAL_SDK_PROVIDER="openai",
                    BCAL_SDK_BASE_URL=sdk_url + "/v1",
                    BCAL_SDK_MODEL=config["inference"]["model"],
                    BCAL_SDK_API_KEY_ENV="BCAL_SDK_PROXY_KEY",
                    BCAL_SDK_MAX_MODEL_REQUESTS="64",
                    BCAL_SDK_TIMEOUT_SECONDS="1200",
                )
                if required_effort is not None:
                    env["BCAL_SDK_REASONING_EFFORT"] = required_effort
            command = [
                sys.executable,
                "-m",
                "bcbench",
                "evaluate",
                "bcal",
                pair["instanceId"],
                "--category",
                pair["category"],
                "--tier",
                pair["tier"],
                "--repo-path",
                str(work / "workspace"),
                "--output-dir",
                str(work / "results"),
                "--run-id",
                "hosted-policy",
            ]
            if runtime == "copilot-sdk":
                command += ["--agent-planning", "copilot"]
            watchdog = max(1, int(1430 - (time.monotonic() - started)))
            with (work / "console.txt").open("w", encoding="utf-8") as console:
                try:
                    _run_bcal_process(command, timeout=watchdog, stdout=console, env=env)
                    attempt["exitCode"] = 0
                except subprocess.CalledProcessError as error:
                    attempt["exitCode"] = error.returncode
                except subprocess.TimeoutExpired:
                    attempt.update(exitCode=None, timeout=True)
                except AgentError:
                    attempt.update(exitCode=None, cleanupVerified=False)
                    raise
            attempt["mainRoute"] = route_receipt(main_audit, required_reasoning_effort=required_effort)
            attempt["auxiliaryRoute"] = route_receipt(chat_audit, required_reasoning_effort=required_effort) if runtime == "copilot-sdk" else None
            attempt["firstModelResponse"] = attempt["mainRoute"]["http200"] > 0
        verify_owned_cleanup(binary)
        verify_package(Path(os.environ["BCAL_STUDY_WORK"]) / "package" / "stage")
        rows = list((work / "results").rglob("*.jsonl"))
        rows = [path for path in rows if path.parent.name != "logs"]
        require(len(rows) == 1, "Missing or ambiguous evaluation result.")
        lines = rows[0].read_text(encoding="utf-8").splitlines()
        require(len(lines) == 1, "Ambiguous evaluation result rows.")
        row = json.loads(lines[0])
        attempt["firstModelResponse"] = model_response_observed(attempt["mainRoute"], row.get("transcript", {}))
        attempt["rawResultSha256"] = digest(rows[0])
        attempt["execution"] = sanitize_row(row, runtime, sdk_catalog_sha256=pair["sdkToolCatalogSha256"])
        if pair["lane"] == "authority":
            attempt["authority"] = authority_projection(row, pair)
        require(pair["lane"] == "authority" or attempt["execution"]["freshCompiled"] is not False or not attempt["execution"]["completed"], "A stale compile cannot be a successful result.")
        dataset = next(item for item in config["datasets"] if item["tier"] == pair["tier"] and item["category"] == pair["category"])
        entry = next(json.loads(line) for line in (ROOT / dataset["file"]).read_text(encoding="utf-8").splitlines() if json.loads(line)["instance_id"] == pair["instanceId"])
        expected = json.loads(symbols_manifest().read_bytes())["files"]
        symbols = work / "workspace" / (".bcal-symbols" if pair["lane"] == "authority" else entry["project_paths"][0]) / ".alpackages"
        require({path.name: digest(path) for path in symbols.glob("*.app")} == {Path(item["path"]).name: item["sha256"] for item in expected}, "Materialized symbols do not match frozen350.")
        attempt["materializedSymbolsVerified"] = True
        candidate_paths = sorted([*work.rglob("*.al"), *rows])
        before = {path: digest(path) for path in candidate_paths}
        time.sleep(2)
        require(all(digest(path) == checksum for path, checksum in before.items()), "Evidence/output mutated after terminal capture.")
        attempt["lateMutationCheckPassed"] = True
        attempt["seconds"] = time.monotonic() - started
        require(attempt["seconds"] <= 1500, "Attempt exceeded its evaluation/capture cap.")
        if not attempt["firstModelResponse"]:
            attempt["status"] = "infrastructure-unscoreable-before-model"
        elif attempt["exitCode"] != 0 or attempt.get("timeout") or not attempt["execution"]["completed"]:
            attempt.update(status="agent-failed", quality=0.0, testPassed=False)
        else:
            require(bool(row.get("output")) and attempt["execution"]["exported"], "A successful row must have actual exported changes.")
            if pair["lane"] == "authority":
                from bcbench.dataset import BCalScenarioEntry

                scenario = BCalScenarioEntry.model_validate(entry)
                job = {"input": scenario.get_task(), "expected": scenario.get_expected_output(), "output": row["output"]}
            else:
                job = {"input": entry["nl_prompt"], "expected": {"assertions": entry["expected"]}, "output": row["output"]}
            write_json(work / "judge-input.json", job)
            with proxy(work, env, "gpt-56-ceres", "chat-completions", "Judge") as (url, audit):
                judge_env = {**env, "BCAL_STUDY_CHAT_URL": url, "JUDGE_MODEL": "gpt-56-ceres"}
                command = [
                    os.environ["BCAL_STUDY_JUDGE_PYTHON"],
                    str(ROOT / "scripts" / "bcal_study_transport.py"),
                    "judge",
                    "--input",
                    str(work / "judge-input.json"),
                    "--output",
                    str(work / "judge-output.json"),
                ]
                with (work / "judge-console.txt").open("w", encoding="utf-8") as console:
                    _run_bcal_process(command, timeout=100, stdout=console, env=judge_env)
                attempt["judgeRoute"] = route_receipt(audit)
                scores = json.loads((work / "judge-output.json").read_bytes())
                require(
                    set(scores) == {"quality", "testPassed", "assertionPass"}
                    and type(scores.get("quality")) in (int, float)
                    and 0 <= scores["quality"] <= 1
                    and type(scores.get("testPassed")) is bool,
                    "Invalid judge measurements.",
                )
                attempt.update(scores)
                attempt["status"] = "judged"
        attempt["cleanupVerified"] = True
    except Exception as error:
        attempt.update(status="evidence-or-infrastructure-error", errorClass=type(error).__name__)
        raise
    finally:
        attempt.setdefault("seconds", time.monotonic() - started)
        attempt["totalIncludingJudgeSeconds"] = time.monotonic() - started
        if runtime == "legacy":
            attempt["legacyDiagnostics"] = {
                "transport": legacy_diagnostic_receipt(work / "HostAgent-chat-completions.audit.diagnostics.json"),
                "bridgeInvocations": [legacy_diagnostic_receipt(path) for path in sorted((work / "bridge-diagnostics").glob("bridge-*.json"))],
                "invocationOrder": "not-established",
            }
        for role, wire in (("main", "responses" if runtime == "copilot-sdk" else "chat-completions"), ("auxiliary", "chat-completions"), ("judge", "chat-completions")):
            path = work / f"{'Judge' if role == 'judge' else 'HostAgent'}-{wire}.audit.json"
            if path.exists():
                try:
                    attempt[f"{role}Route"] = route_receipt(path, required_reasoning_effort=config["inference"]["reasoning"] if role != "judge" else None)
                except ValueError as error:
                    attempt["routingFailure"] = type(error).__name__
                    attempt[f"{role}RouteFailure"] = route_failure_diagnostics(path)
                    attempt.update(status="evidence-or-infrastructure-error", quality=None, testPassed=None)
        main_counters = attempt.get("mainRouteFailure", {}).get("counters", attempt.get("mainRoute", {}))
        main_responses = main_counters.get("http200")
        attempt["modelBacked"] = main_responses > 0 if type(main_responses) is int else None
        request_counts = [
            attempt.get(f"{role}RouteFailure", {}).get("counters", attempt.get(f"{role}Route", {})).get("requests") for role in (("main", "auxiliary") if runtime == "copilot-sdk" else ("main",))
        ]
        attempt["upstreamRequests"] = sum(request_counts) if all(type(count) is int for count in request_counts) else None
        if attempt["seconds"] > 1500:
            attempt.update(status="over-cap-invalid", quality=None, testPassed=None)
        write_json(public, attempt)
    return attempt


def run_pair(args: argparse.Namespace) -> None:
    config = study()
    verify_runtime_diagnostics_proof()
    verify_runtime_effort_proof()
    pair = pairs()[args.pair]
    started = float(os.environ.get("BCAL_STUDY_JOB_STARTED_UNIX", time.time()))
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""), "LLM_API_ENVIRONMENT": "TEST"}
    receipt = {
        "studyId": config["studyId"],
        "pair": pair,
        "status": "setup",
        "grantSeconds": config.get("pairTimeoutSeconds", config.get("budget", {}).get("pairReservationSeconds")),
        "admitted": [],
        "benchCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "inputsSha256": digest(INPUTS / "study.json"),
    }
    path = args.output / f"pair-{args.pair}.json"
    write_json(path, receipt)
    try:
        prepare_package(args.work / "package")
        verify_symbols()
        for runtime in pair["order"]:
            require(time.time() - started + 1500 + 100 <= receipt["grantSeconds"] - 30, "Do not admit work without full attempt, judge and cleanup reservations.")
            receipt["admitted"].append(runtime)
            write_json(path, receipt)
            result = run_attempt(pair, runtime, args.work / f"pair-{args.pair}" / runtime, env, args.output / f"attempt-{args.pair}-{runtime}.json")
            require(result["status"] in ("judged", "agent-failed") and result.get("cleanupVerified") is True, "Stop after an invalid/unverified attempt; no retries.")
        receipt["status"] = "finished"
    except Exception as error:
        receipt.update(status="incomplete", errorClass=type(error).__name__)
        raise
    finally:
        receipt["jobElapsedSeconds"] = time.time() - started
        write_json(path, receipt)


def summary(args: argparse.Namespace) -> None:
    config = study()
    expected = {(pair["index"], runtime): pair for pair in pairs() for runtime in pair["order"]}
    records = {}
    for path in args.work.rglob("attempt-*.json"):
        row = json.loads(path.read_bytes())
        key = (row["index"], row["runtime"])
        require(key in expected and key not in records, "Duplicate or out-of-scope hosted attempt.")
        require(row["inputsSha256"] == digest(INPUTS / "study.json") and row["studyId"] == config["studyId"], "Mixed study identity.")
        require(all(row[name] == expected[key][name] for name in ("category", "lane", "tier", "instanceId", "repeat")), "Mixed pair identity.")
        records[key] = row
    scoreable = [row for row in records.values() if row.get("status") in ("judged", "agent-failed") and row.get("firstModelResponse") is True]
    missing = [{"pair": key[0], "runtime": key[1]} for key in expected if key not in records]
    lanes = sorted({pair["lane"] for pair in expected.values()})
    expected_count = len(expected)
    result = {
        "studyId": config["studyId"],
        "inputsSha256": digest(INPUTS / "study.json"),
        "benchCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "mainModel": config["inference"]["model"],
        "reasoningEffort": config["inference"]["reasoning"],
        "judgeModel": config["judge"]["model"],
        "package": config["package"],
        "symbolsManifestSha256": config["symbolsManifestSha256"],
        "kind": "descriptive-policy-comparison-not-noninferiority",
        "expected": expected_count,
        "captured": len(records),
        "scoreable": len(scoreable),
        "complete": len(scoreable) == expected_count,
        "missing": missing,
        "attempts": list(records.values()),
        "lanes": {
            lane: {
                runtime: {
                    "expected": sum(pair["lane"] == lane for pair in pairs()),
                    "captured": sum(row["lane"] == lane and row["runtime"] == runtime for row in records.values()),
                    "judged": sum(row["lane"] == lane and row["runtime"] == runtime and row["status"] == "judged" for row in records.values()),
                    "modelBacked": sum(row["lane"] == lane and row["runtime"] == runtime and row.get("modelBacked") is True for row in records.values()),
                    "modelBackedUnknown": sum(row["lane"] == lane and row["runtime"] == runtime and row.get("modelBacked") is None for row in records.values()),
                    "agentFailed": sum(row["lane"] == lane and row["runtime"] == runtime and row["status"] == "agent-failed" for row in records.values()),
                    "timeouts": sum(row["lane"] == lane and row["runtime"] == runtime and row.get("timeout") is True for row in records.values()),
                    "domainCompleted": sum(row["lane"] == lane and row["runtime"] == runtime and row.get("execution", {}).get("completed") is True for row in records.values()),
                    "exported": sum(row["lane"] == lane and row["runtime"] == runtime and row.get("execution", {}).get("exported") is True for row in records.values()),
                    "freshCompiled": sum(row["lane"] == lane and row["runtime"] == runtime and row.get("execution", {}).get("freshCompiled") is True for row in records.values()),
                    "freshCompileUnknown": sum(row["lane"] == lane and row["runtime"] == runtime and row.get("execution", {}).get("freshCompiled") is None for row in records.values()),
                    "qualityPasses": sum(row["lane"] == lane and row["runtime"] == runtime and row.get("testPassed") is True for row in records.values()),
                    "deterministicAuthorityPasses": sum(
                        row["lane"] == lane and row["runtime"] == runtime and row.get("authority", {}).get("deterministicCompliant") is True for row in records.values()
                    )
                    if lane == "authority"
                    else None,
                }
                for runtime in config["variants"]
            }
            for lane in lanes
        },
        "historicalLocalBudget": config.get("budget", config.get("historicalAccounting")),
        "limitations": [
            "Same source/package; intentional planning/prompt/catalog and Responses-vs-chat differences, not pure runtime parity.",
            f"One repeat/{len(pairs())} fixed cases, separate lanes. Descriptive results, not noninferiority, production readiness or a policy-scan claim.",
            "Main+auxiliary+judge tickets are session-local memory only; new persistent legacy/judge routing differs from historical per-process empty-ticket adapters.",
            "Provider cost is unavailable. Token subtotals may be incomplete; unavailable is null, never measured zero.",
            "Only sanitized identity/numeric/boolean/hash evidence retained publicly. Raw AL/prompts/private receipts/package/certificate never published; ephemeral runner-local raw files expire with runner.",
            "The original local120-slot pilot is paused/incomplete, not resumed, replaced or pooled. Infrastructure-invalid original and linked replacement/full charge retained; unresolved016 remains unscored with1500s held.",
            "Practical job timeouts include setup/evaluation/judge/artifact/controller time; final Actions job start/end accounting is required after terminal completion, including preflight and failures.",
        ],
    }
    lines = [
        "# Governed BCAL policy comparison",
        "",
        f"Captured **{len(records)}/{expected_count}**, scoreable **{len(scoreable)}/{expected_count}**. {'Complete descriptive study.' if result['complete'] else 'INCOMPLETE; no complete-comparison claim.'}",
        "",
        "| Lane | Pair | Runtime | Status | Quality | Authority compliance | Seconds |",
        "|---|---|---|---|---:|---|---:|",
    ]
    for key in expected:
        row = records.get(key, {})
        quality = row.get("quality")
        lines.append(
            f"| {expected[key]['lane']} | {key[0]} | {key[1]} | {row.get('status', 'not-admitted')} | {quality if quality is not None else 'unavailable'} | {row.get('authority', {}).get('deterministicCompliant', 'N/A')} | {row.get('seconds', 'unavailable')} |"
        )
    lines += ["", *result["limitations"]]
    write_json(args.output / "comparison.json", result)
    (args.output / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    require(result["complete"], "Coverage is incomplete; retain all missing/invalid cells.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("matrix", "fixtures", "runtime-proofs", "preflight", "routing-preflight", "explicit-none-probe", "pair", "summary"))
    parser.add_argument("--work", type=Path, default=Path(os.environ.get("BCAL_STUDY_WORK", ".bcal-study-private")))
    parser.add_argument("--output", type=Path, default=Path("study-sanitized"))
    parser.add_argument("--pair", type=int)
    args = parser.parse_args()
    try:
        if args.command == "fixtures":
            fixtures(args)
        elif args.command == "runtime-proofs":
            sys.stdout.write(json.dumps({"runtimeEffortProof": verify_runtime_effort_proof(), "runtimeDiagnosticsProof": verify_runtime_diagnostics_proof()}) + "\n")
        elif args.command == "matrix":
            sys.stdout.write(json.dumps({"include": [{"pair": row["index"]} for row in pairs()]}) + "\n")
        elif args.command == "preflight":
            preflight(args)
        elif args.command == "routing-preflight":
            routing_preflight(args)
        elif args.command == "explicit-none-probe":
            routing_preflight(args, explicit_none_probe=True)
        elif args.command == "summary":
            summary(args)
        elif args.pair is None:
            parser.error("--pair is required")
        else:
            require(0 <= args.pair < len(pairs()), "Pair index is outside the immutable selection.")
            run_pair(args)
    except Exception as error:  # noqa: BLE001 - public logs must never contain private upstream bodies or generated code
        sys.stderr.write(f"Study {args.command} stopped: {type(error).__name__}\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
