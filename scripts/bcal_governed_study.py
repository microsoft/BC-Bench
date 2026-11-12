"""Bounded same-package policy validation; usable locally without GitHub Actions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "experiments" / "bcal-sdk-policy"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def study() -> dict:
    value = json.loads((INPUTS / "study.json").read_bytes())
    budget = value["budget"]
    reserved = budget["preflightReservationSeconds"] + budget["controllerReservationSeconds"] + budget["pairCount"] * budget["pairReservationSeconds"] + budget["summaryReservationSeconds"]
    if reserved > 28800 or budget["historicalMeasuredSeconds"] + budget["unresolvedLocalReservationSeconds"] + 28800 > budget["originalEnvelopeSeconds"]:
        raise ValueError("Aggregate budget does not fit the approved carry-forward envelope.")
    if digest(INPUTS / "symbols.json") != value["symbolsManifestSha256"]:
        raise ValueError("Symbol manifest changed.")
    return value


def pairs() -> list[dict]:
    result = []
    for dataset in study()["datasets"]:
        path = ROOT / dataset["file"]
        if digest(path) != dataset["datasetSha256"]:
            raise ValueError("Dataset changed.")
        data = {row["instance_id"]: row for line in path.read_text(encoding="utf-8").splitlines() if line for row in [json.loads(line)]}
        for selected in dataset["selectedEntries"]:
            row = data[selected["instanceId"]]
            prompt = hashlib.sha256(row["nl_prompt"].encode()).hexdigest()
            expected = hashlib.sha256(json.dumps(row["expected"], sort_keys=True).encode()).hexdigest()
            if prompt != selected["taskPromptSha256"] or expected != selected["expectedSha256"]:
                raise ValueError("Entry prompt or assertions changed.")
            index = len(result) // 2
            for repeat in (1, 2):
                order = ["legacy", "copilot-sdk"] if (index + repeat) % 2 else ["copilot-sdk", "legacy"]
                result.append({"index": len(result), "tier": dataset["tier"], "instanceId": row["instance_id"], "repeat": repeat, "order": order})
    if len(result) != 8:
        raise ValueError("Only eight fixed pairs are admitted.")
    return result


def verify_symbols() -> dict:
    manifest = json.loads((INPUTS / "symbols.json").read_bytes())
    root = Path(os.environ.get("BCAL_STUDY_SYMBOL_CACHE", r"C:\bcartifacts.cache\sandbox")) / manifest["cacheVersion"]
    expected = {item["path"]: item["sha256"] for item in manifest["files"]}
    observed = {str(path.relative_to(root)): digest(path) for path in root.rglob("*.app")}
    if len(expected) != 350 or expected != observed:
        raise ValueError("Expected the exact350 frozen symbols, not Latest.")
    roots = sorted(root.parent.glob("28.0.*"), key=lambda item: tuple(map(int, item.name.split("."))))
    if roots[-1] != root:
        raise ValueError("Pipeline would select a different28.0 symbol cache.")
    return {"count": 350, "setSha256": manifest["setSha256"], "manifestSha256": digest(INPUTS / "symbols.json")}


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
        import base64

        feed = os.environ["BCAL_STUDY_FEED"]
        token = os.environ["BCAL_STUDY_ADO_TOKEN"]
        header = {"Authorization": "Basic " + base64.b64encode(("anything:" + token).encode()).decode()}

        def download(url: str, output: Path | None = None) -> dict | None:
            with urllib.request.urlopen(urllib.request.Request(url, headers=header), timeout=90) as response:
                if output is None:
                    return json.load(response)
                with output.open("xb") as stream:
                    shutil.copyfileobj(response, stream)
            return None

        index = download(feed)
        require(isinstance(index, dict), "Missing NuGet service index.")
        base = next(item["@id"] for item in index["resources"] if str(item["@type"]).startswith("PackageBaseAddress/"))
        name, version = config["id"].lower(), config["version"]
        download(f"{base.rstrip('/')}/{name}/{version}/{name}.{version}.nupkg", package)
    if package.stat().st_size != config["bytes"] or digest(package) != config["sha256"]:
        raise ValueError("New or corrupt package bytes are not admitted.")
    stage = folder / "stage"
    if not stage.exists():
        with zipfile.ZipFile(package) as archive:
            files = [entry for entry in archive.infolist() if not entry.is_dir()]
            if len(files) != 460 or any(not (stage / entry.filename).resolve().is_relative_to(stage.resolve()) for entry in files):
                raise ValueError("Unexpected governed archive inventory.")
            archive.extractall(stage)
    binary = verify_package(stage)
    return {"sha256": config["sha256"], "sourceCommitSha": config["sourceCommitSha"], "framework": "net10.0", "versionVerified": True, "binarySha256": digest(binary)}


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
        receipt["package"] = prepare_package(args.work / "package")
        receipt["symbols"] = verify_symbols()
        receipt["pairCount"] = len(pairs())
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
def proxy(work: Path, env: dict[str, str], model: str, wire: str, step: str) -> Iterator[tuple[str, Path]]:
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


def route_receipt(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if set(value) != {"requests", "http200", "ticketsReturned", "ticketsReplayed", "sessionStable", "modelStable"}:
        raise ValueError("Unexpected route receipt.")
    if (
        any(type(value[key]) is not int or value[key] < 0 for key in ("requests", "http200", "ticketsReturned", "ticketsReplayed"))
        or value["sessionStable"] is not True
        or value["modelStable"] is not True
    ):
        raise ValueError("Invalid route counters.")
    if value["requests"] > 1 and value["http200"] and not value["ticketsReplayed"]:
        raise ValueError("No cross-turn sticky route proof.")
    return value


def trace_projection(transcript: dict) -> dict:
    trace = transcript.get("evidence", {}).get("trace", {})
    require(trace.get("truncated") is False and trace.get("omittedEventCount") == 0 and isinstance(trace.get("events"), list), "Canonical trace is missing or truncated.")
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
    }
    events = []
    for event in trace["events"]:
        safe = {key: event[key] for key in ("sequence", "turn", "iteration", "inputLength", "requestedToolCallCount", "succeeded") if type(event.get(key)) in (int, bool)}
        safe["type"] = event["type"] if event.get("type") in types else "other-event"
        for key in ("toolName", "operation", "inputHash", "callId", "fromState", "toState", "status"):
            if isinstance(event.get(key), str):
                safe[key + "Sha256"] = hashlib.sha256(event[key].encode()).hexdigest()
        events.append(safe)
    return {
        "truncated": False,
        "omittedEventCount": 0,
        "events": events,
        "contentProjection": "numeric-and-hash-only",
        "originalTraceSha256": hashlib.sha256(json.dumps(trace, sort_keys=True).encode()).hexdigest(),
    }


def verify_owned_cleanup(binary: Path) -> None:
    if os.name == "nt":
        env = {**os.environ, "BCAL_STUDY_PROCESS_ROOT": str(binary.parent) + os.sep}
        script = "@(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($env:BCAL_STUDY_PROCESS_ROOT, [StringComparison]::OrdinalIgnoreCase) }).Count"
        count = subprocess.check_output(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env, text=True, timeout=15).strip()
        require(count == "0", "An owned packaged runtime process remains; stop admissions.")


def sanitize_row(row: dict, runtime: str) -> dict:
    from bcbench.agent.bcal.agent import BCalBackendConfig, _require_completed, _result_metrics
    from bcbench.types import BCalAgentPlanning, BCalAgentRuntime

    transcript = row["transcript"]
    identity = transcript["runtimeIdentity"]
    config = BCalBackendConfig(
        command="governed-memory-only-chat-route",
        model="gpt-55-chat",
        agent_runtime=BCalAgentRuntime(runtime),
        agent_planning=BCalAgentPlanning.COPILOT if runtime == "copilot-sdk" else None,
        sdk_provider="openai" if runtime == "copilot-sdk" else None,
        sdk_model="gpt-55-chat" if runtime == "copilot-sdk" else None,
        sdk_max_model_requests=64 if runtime == "copilot-sdk" else None,
        sdk_timeout_seconds=1200 if runtime == "copilot-sdk" else None,
        inference_provider="bc-eval-m365-test@0.6.1",
        llm_provider="bc-eval-m365-test@0.6.1",
        llm_wire_api="chat-completions",
    )
    expected = config.planning_identity()
    if identity.get("agentRuntime") != runtime or any(key not in identity or identity[key] != value for key, value in expected.items()):
        raise ValueError("Observed planning policy mismatch.")
    source = transcript.get("sourceCommitSha") or transcript.get("executionIdentity", {}).get("sourceCommitSha")
    if source != study()["package"]["sourceCommitSha"]:
        raise ValueError("Observed package source mismatch.")
    safe = {"policy": expected, "completed": False, "freshCompiled": None, "exported": False, "usage": {}, "identityHashes": {}}
    metrics = _result_metrics(transcript, 0)
    safe["usage"] = {"promptTokens": metrics.prompt_tokens, "completionTokens": metrics.completion_tokens, "totalTokens": metrics.total_tokens, "cost": None}
    safe["toolUsageByNameHash"] = {hashlib.sha256(key.encode()).hexdigest(): value for key, value in (metrics.tool_usage or {}).items()}
    safe["canonicalTrace"] = trace_projection(transcript)
    for key in ("systemPromptSha256", "toolCatalogSha256"):
        value = identity.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("Missing or invalid prompt/catalog hash.")
        safe["identityHashes"][key] = value
    if runtime == "copilot-sdk" and (identity.get("sdkPackageVersion"), identity.get("sdkRuntimeVersion"), identity["toolCatalogSha256"]) != (
        "1.0.29",
        "1.0.107",
        study()["package"]["nativeCatalogSha256"],
    ):
        raise ValueError("Observed SDK/catalog identity mismatch.")
    evidence = transcript.get("agentRuntimeEvidence") or []
    if evidence:
        final = evidence[-1]
        safe["freshCompiled"] = final.get("compileCoversLatestChange") if type(final.get("compileCoversLatestChange")) is bool else None
    if not row.get("error_message") and row.get("timeout") is not True:
        _require_completed(transcript, metrics=metrics, config=config.experiment(1500, transcript))
        safe["completed"] = True
        safe["exported"] = transcript.get("export", {}).get("success") is True
    safe["timeout"] = row.get("timeout") is True
    return safe


def run_attempt(pair: dict, runtime: str, work: Path, env: dict[str, str], public: Path) -> dict:
    from bcbench_core.exceptions import AgentError

    from bcbench.agent.bcal.agent import _run_bcal_process

    config = study()
    work.mkdir(parents=True)
    attempt = {
        **{key: pair[key] for key in ("index", "tier", "instanceId", "repeat")},
        "studyId": config["studyId"],
        "inputsSha256": digest(INPUTS / "study.json"),
        "benchCommit": os.environ.get("GITHUB_SHA"),
        "runtime": runtime,
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
        env = {key: value for key, value in env.items() if not key.startswith("BCAL_")}
        env.update(
            PATH=str(binary.parent) + os.pathsep + os.environ["PATH"],
            BCAL_AGENT_RUNTIME=runtime,
            BCAL_LLM_MODEL="gpt-55-chat",
            BCAL_LLM_PROVIDER="bc-eval-m365-test@0.6.1",
            BCAL_LLM_WIRE_API="chat-completions",
            BCAL_INFERENCE_PROVIDER="bc-eval-m365-test@0.6.1",
            BCAL_SDK_PROXY_KEY=secrets.token_urlsafe(32),
            BCAL_LLM_COMMAND=subprocess.list2cmdline([os.environ["BCAL_STUDY_INFERENCE_PYTHON"], str(ROOT / "scripts" / "bcal_study_transport.py"), "bridge"]),
        )
        with ExitStack() as stack:
            chat_url, chat_audit = stack.enter_context(proxy(work, env, "gpt-55-chat", "chat-completions", "HostAgent"))
            env["BCAL_STUDY_CHAT_URL"] = chat_url
            main_audit = chat_audit
            if runtime == "copilot-sdk":
                sdk_url, main_audit = stack.enter_context(proxy(work, env, "gpt-55-chat", "responses", "HostAgent"))
                env.update(
                    BCAL_SDK_PROVIDER="openai",
                    BCAL_SDK_BASE_URL=sdk_url + "/v1",
                    BCAL_SDK_MODEL="gpt-55-chat",
                    BCAL_SDK_API_KEY_ENV="BCAL_SDK_PROXY_KEY",
                    BCAL_SDK_MAX_MODEL_REQUESTS="64",
                    BCAL_SDK_TIMEOUT_SECONDS="1200",
                )
            command = [
                sys.executable,
                "-m",
                "bcbench",
                "evaluate",
                "bcal",
                pair["instanceId"],
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
            attempt["mainRoute"] = route_receipt(main_audit)
            attempt["auxiliaryRoute"] = route_receipt(chat_audit) if runtime == "copilot-sdk" else None
            attempt["firstModelResponse"] = attempt["mainRoute"]["http200"] > 0
        verify_owned_cleanup(binary)
        verify_package(Path(os.environ["BCAL_STUDY_WORK"]) / "package" / "stage")
        rows = list((work / "results").rglob("*.jsonl"))
        rows = [path for path in rows if path.parent.name != "logs"]
        require(len(rows) == 1, "Missing or ambiguous evaluation result.")
        lines = rows[0].read_text(encoding="utf-8").splitlines()
        require(len(lines) == 1, "Ambiguous evaluation result rows.")
        row = json.loads(lines[0])
        attempt["firstModelResponse"] = attempt["firstModelResponse"] and any(
            type(turn.get("modelRequests")) is int and turn["modelRequests"] > 0 for turn in row.get("transcript", {}).get("agentRuntimeEvidence", [])
        )
        attempt["rawResultSha256"] = digest(rows[0])
        attempt["execution"] = sanitize_row(row, runtime)
        require(attempt["execution"]["freshCompiled"] is not False or not attempt["execution"]["completed"], "A stale compile cannot be a successful result.")
        dataset = next(item for item in config["datasets"] if item["tier"] == pair["tier"])
        entry = next(json.loads(line) for line in (ROOT / dataset["file"]).read_text(encoding="utf-8").splitlines() if json.loads(line)["instance_id"] == pair["instanceId"])
        expected = json.loads((INPUTS / "symbols.json").read_bytes())["files"]
        symbols = work / "workspace" / entry["project_paths"][0] / ".alpackages"
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
        if attempt["seconds"] > 1500:
            attempt.update(status="over-cap-invalid", quality=None, testPassed=None)
        write_json(public, attempt)
    return attempt


def run_pair(args: argparse.Namespace) -> None:
    config = study()
    pair = pairs()[args.pair]
    started = float(os.environ.get("BCAL_STUDY_JOB_STARTED_UNIX", time.time()))
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""), "LLM_API_ENVIRONMENT": "TEST"}
    receipt = {
        "studyId": config["studyId"],
        "pair": pair,
        "status": "setup",
        "grantSeconds": config["budget"]["pairReservationSeconds"],
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
            require(time.time() - started + 1500 + 100 <= config["budget"]["pairReservationSeconds"] - 30, "Do not admit work without full attempt, judge and cleanup reservations.")
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
        require(all(row[name] == expected[key][name] for name in ("tier", "instanceId", "repeat")), "Mixed pair identity.")
        records[key] = row
    scoreable = [row for row in records.values() if row.get("status") in ("judged", "agent-failed") and row.get("firstModelResponse") is True]
    missing = [{"pair": key[0], "runtime": key[1]} for key in expected if key not in records]
    result = {
        "studyId": config["studyId"],
        "kind": "descriptive-policy-comparison-not-noninferiority",
        "expected": 16,
        "captured": len(records),
        "scoreable": len(scoreable),
        "complete": len(scoreable) == 16,
        "missing": missing,
        "attempts": list(records.values()),
        "historicalLocalBudget": config["budget"],
        "limitations": [
            "Same source/package; intentional planning/prompt/catalog and Responses-vs-chat differences, not pure runtime parity.",
            "Two repeats/four fixed cases only; no noninferiority, production readiness, full-dataset or policy-scan claim.",
            "Main+auxiliary+judge tickets are session-local memory only; new persistent legacy/judge routing differs from historical per-process empty-ticket adapters.",
            "Provider cost is unavailable. Token subtotals may be incomplete; unavailable is null, never measured zero.",
            "Only sanitized identity/numeric/boolean/hash evidence retained publicly. Raw AL/prompts/private receipts/package/certificate never published; ephemeral runner-local raw files expire with runner.",
            "The original local120-slot pilot is paused/incomplete, not resumed, replaced or pooled. Infrastructure-invalid original and linked replacement/full charge retained; unresolved016 remains unscored with1500s held.",
            "Static disjoint job grants count setup/evaluation/judge/artifact/controller time; final Actions job start/end accounting is required after terminal completion, including preflight and failures.",
        ],
    }
    lines = [
        "# Governed BCAL policy comparison",
        "",
        f"Captured **{len(records)}/16**, scoreable **{len(scoreable)}/16**. {'Complete descriptive study.' if result['complete'] else 'INCOMPLETE; no complete-comparison claim.'}",
        "",
        "| Pair | Runtime | Status | Quality | Fresh compile | Seconds |",
        "|---|---|---|---:|---|---:|",
    ]
    for key in expected:
        row = records.get(key, {})
        quality = row.get("quality")
        lines.append(
            f"| {key[0]} | {key[1]} | {row.get('status', 'not-admitted')} | {quality if quality is not None else 'unavailable'} | {row.get('execution', {}).get('freshCompiled')} | {row.get('seconds', 'unavailable')} |"
        )
    lines += ["", *result["limitations"]]
    write_json(args.output / "comparison.json", result)
    (args.output / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    require(result["complete"], "Coverage is incomplete; retain all missing/invalid cells.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("matrix", "preflight", "pair", "summary"))
    parser.add_argument("--work", type=Path, default=Path(os.environ.get("BCAL_STUDY_WORK", ".bcal-study-private")))
    parser.add_argument("--output", type=Path, default=Path("study-sanitized"))
    parser.add_argument("--pair", type=int, choices=range(8))
    args = parser.parse_args()
    try:
        if args.command == "matrix":
            sys.stdout.write(json.dumps({"include": [{"pair": row["index"]} for row in pairs()]}) + "\n")
        elif args.command == "preflight":
            preflight(args)
        elif args.command == "summary":
            summary(args)
        elif args.pair is None:
            parser.error("--pair is required")
        else:
            run_pair(args)
    except Exception as error:  # noqa: BLE001 - public logs must never contain private upstream bodies or generated code
        sys.stderr.write(f"Study {args.command} stopped: {type(error).__name__}\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
