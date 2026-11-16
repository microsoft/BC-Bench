"""Opt-in single-package reasoning smoke and one bounded gold repetition."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

from bcal_reasoning_budget import StudyBudget
from bcal_reasoning_coding import (
    MODELS,
    SCORER_SHA,
    AdmissionError,
    CodingPolicy,
    CodingRun,
    ProviderBudget,
    coding_command,
    process_environment,
    provider_route,
    score_checklist,
    transcript_summary,
    verify_auxiliary_command,
    write_json,
)
from bcal_reasoning_compatibility import CLIENT_SHA
from bcal_reasoning_package import PROFILE, ROOT, load_pin
from bcal_reasoning_smoke import SYMBOL_MANIFEST_SHA, TASK, materialize_symbols

SELECTOR = ROOT / "experiments" / "bcal-full-gold" / "study.json"
SELECTOR_SHA = "1e9c638a70aa8a5e45deb3716dae5a48705910ade71f1dca3f6f24c221776f86"
DATASET_SHA = "fce1a4c1d4b63d9b593b5d8c2c14a65727c5c6063dc0cf5d754208619aac4ab9"
SEMANTIC_WORKERS = 4
JUDGE_WORKERS = 2


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: object, message: str) -> None:
    if not value:
        raise AdmissionError(message)


def frozen_entries() -> list[dict]:
    require(sha(SELECTOR) == SELECTOR_SHA, "Frozen gold selector changed.")
    profile = json.loads(SELECTOR.read_bytes())
    (dataset,) = profile["datasets"]
    path = ROOT / dataset["file"]
    require(sha(path) == dataset["datasetSha256"] == DATASET_SHA, "Frozen dataset changed.")
    data = {row["instance_id"]: row for line in path.read_text(encoding="utf-8").splitlines() if line for row in [json.loads(line)]}
    require(len(data) == len(dataset["selectedEntries"]) == 110 and set(data) == {row["instanceId"] for row in dataset["selectedEntries"]}, "Exactly the frozen 110 cases are required.")
    result = []
    for selected in dataset["selectedEntries"]:
        entry = data[selected["instanceId"]]
        require(hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest() == selected["entrySha256"], "Frozen entry changed.")
        require(hashlib.sha256(entry["nl_prompt"].encode()).hexdigest() == selected["taskPromptSha256"], "Frozen prompt changed.")
        require(hashlib.sha256(json.dumps(entry["expected"], sort_keys=True).encode()).hexdigest() == selected["expectedSha256"], "Frozen assertions changed.")
        require(entry["environment_setup_version"] == selected["environmentSetupVersion"] == "28.0", "Frozen symbol version changed.")
        result.append(entry)
    return result


def binding() -> dict:
    require(os.environ.get("GITHUB_SHA"), "Hosted source identity is required.")
    return {
        "benchCommit": os.environ["GITHUB_SHA"],
        "packageProfileSha256": sha(PROFILE),
        "runnerSha256": sha(Path(__file__)),
        "transportSha256": sha(ROOT / "scripts" / "bcal_reasoning_coding.py"),
        "budgetSha256": sha(ROOT / "scripts" / "bcal_reasoning_budget.py"),
        "packageVerifierSha256": sha(ROOT / "scripts" / "bcal_reasoning_package.py"),
        "selectorSha256": SELECTOR_SHA,
        "datasetSha256": DATASET_SHA,
        "symbolManifestSha256": SYMBOL_MANIFEST_SHA,
        "models": list(MODELS),
        "requestedEffort": "medium",
        "auxiliary": "forbidden",
        "judgeModel": "gpt-56-ceres",
        "judgeEffort": "omitted",
        "codingHttpPerCell": 64,
        "judgeHttpPerCell": 1,
        "totalHttp": 21450,
        "semanticWorkers": SEMANTIC_WORKERS,
        "judgeWorkers": JUDGE_WORKERS,
    }


def binding_id(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def verify_symbols(path: Path, expected: list[dict]) -> None:
    require({item.name: sha(item) for item in path.glob("*.app")} == {Path(item["path"]).name: item["sha256"] for item in expected}, "Exact symbol bytes differ.")


def prepare_symbols(cache: Path, target: Path, gold: bool) -> list[dict]:
    manifest_path = ROOT / "experiments" / "bcal-sdk-policy" / "symbols.json"
    require(sha(manifest_path) == SYMBOL_MANIFEST_SHA, "Frozen symbol manifest changed.")
    manifest = json.loads(manifest_path.read_bytes())
    if not gold:
        return materialize_symbols(cache, target)["selectedFiles"]
    require(len(manifest["files"]) == 350, "Gold requires 350 exact symbol archives.")
    target.mkdir()
    for row in manifest["files"]:
        source = cache / manifest["cacheVersion"] / row["path"]
        require(source.stat().st_size == row["bytes"] and sha(source) == row["sha256"], "Frozen source symbol differs.")
        shutil.copyfile(source, target / Path(row["path"]).name)
    verify_symbols(target, manifest["files"])
    return manifest["files"]


def validate_tool_proof(path: Path, pin: dict, tool: str) -> None:
    proof = json.loads(path.read_bytes())
    identity = proof["identity"]
    require(
        identity["kind"] == "exact-governed-package"
        and identity["version"] == pin["version"]
        and identity["source"] == pin["source"]
        and identity["archiveSha256"] == pin["archive_sha256"]
        and identity["verifiedRuntimeFiles"] == pin["runtime_files"]
        and proof["forcedTool"] == tool
        and proof["providerAttempts"] == 0
        and proof["offlineRequests"] == 2
        and proof["secondRequestContainsToolResult"] is True
        and proof["packagePayloadUnchanged"] is True
        and proof["auxiliaryInvocations"] == 0
        and proof["terminalEvidence"]["failureMessageSignature"] != "callback_fence_guard",
        "Actual package reset/control proof is not admitted.",
    )


def verify_toolchain(gold: bool) -> dict:
    distribution = importlib.metadata.distribution("bc-eval")
    client = Path(distribution.locate_file("bc_eval/llm/llm_api.py"))
    require(distribution.version == "0.6.1" and sha(client) == CLIENT_SHA, "Pinned provider client differs.")
    result = {"providerClientSha256": sha(client)}
    if not gold:
        return result
    scorer = Path(distribution.locate_file("bc_eval/scorers/autoeval/lmchecklist.py"))
    autoevals = importlib.metadata.distribution("autoevals")
    retry_owner = Path(autoevals.locate_file("autoevals/oai.py"))
    require(
        sha(scorer) == SCORER_SHA and autoevals.version == "0.1.0" and sha(retry_owner) == "9b8cc1f7226346f197863daba6d872701fb2e2fbbb50480ae5ad509fa53190c1",
        "Pinned judge or higher-level retry owner differs.",
    )
    return {**result, "scorerSha256": sha(scorer), "retryOwnerSha256": sha(retry_owner)}


def admit(args: argparse.Namespace) -> None:
    from bcal_reasoning_compatibility import native_probe

    gold = args.phase == "admit-gold"
    toolchain = verify_toolchain(gold)
    pin = load_pin()
    pin.verify(args.package, args.archive)
    args.work.mkdir(parents=True, exist_ok=False)
    args.output.mkdir(parents=True, exist_ok=False)
    validate_tool_proof(args.reset_proof, pin.model_dump(), "start_new_work")
    validate_tool_proof(args.control_proof, pin.model_dump(), "list_files")
    verify_auxiliary_command(process_environment())
    proofs = []
    for model in MODELS:
        output = args.output / f"native-{model}.json"
        proof = native_probe(args.package, args.helper, model, "medium", "offline", output, "offline")
        require(
            proof.get("outcome") == "response_received"
            and proof.get("boundaryRequests") == 1
            and proof.get("boundaryBlocked") == 0
            and proof.get("appliedEffort") == "medium"
            and proof.get("wire", {}).get("model") == model
            and proof.get("wire", {}).get("reasoning", {}).get("effort") == "medium",
            "Actual packaged native medium request generation failed.",
        )
        proofs.append({"model": model, "sha256": sha(output)})
    symbols = prepare_symbols(args.symbol_cache, args.work / "symbols", gold)
    value = binding()
    if gold:
        frozen_entries()
        smoke = json.loads(args.smoke_receipt.read_bytes())
        require(
            smoke["status"] == "completed"
            and smoke["benchCommit"] == os.environ["GITHUB_SHA"]
            and smoke["package"] == pin.model_dump()
            and smoke["policy"]["model"] == MODELS[0]
            and smoke["policy"]["requestedEffort"] == "medium"
            and smoke["freshCompiled"] is True
            and smoke["exported"] is True
            and smoke["auxiliaryInvocations"] == 0
            and 0 < smoke["providerAttempts"] <= 30
            and smoke["providerAttempts"] == len(smoke["accounting"]["events"])
            and smoke["runtimeCleanupVerified"] is True
            and smoke["accounting"]["stopped"] is False
            and all(event.get("httpStatus") == 200 and event["wireEffort"] == {"presence": "explicit", "value": "medium"} for event in smoke["accounting"]["events"]),
            "Successful new-package Sol compile/export smoke is required before gold.",
        )
    write_json(
        args.output / "admission.json",
        {
            "status": "admitted",
            "binding": value,
            "bindingId": binding_id(value),
            "package": pin.model_dump(),
            "symbols": symbols,
            "gold": gold,
            "nativeProofs": proofs,
            "toolchain": toolchain,
            "helperSha256": sha(args.helper),
            "resetProofSha256": sha(args.reset_proof),
            "controlProofSha256": sha(args.control_proof),
            "smokeReceiptSha256": sha(args.smoke_receipt) if gold else None,
            "providerAttempts": 0,
        },
    )


def verify_admission(args: argparse.Namespace, gold: bool) -> dict:
    value = json.loads((args.output / "admission.json").read_bytes())
    require(value["status"] == "admitted" and value["gold"] is gold and value["binding"] == binding() and value["bindingId"] == binding_id(binding()), "Current source admission differs.")
    require(value["package"] == load_pin().model_dump(), "Admitted package changed.")
    require(value["toolchain"] == verify_toolchain(gold), "Admitted provider/judge toolchain changed.")
    load_pin().verify(args.package, args.archive)
    verify_symbols(args.work / "symbols", value["symbols"])
    require(sha(args.helper) == value["helperSha256"], "Native helper changed.")
    for proof in value["nativeProofs"]:
        require(sha(args.output / f"native-{proof['model']}.json") == proof["sha256"], "Native wire proof changed.")
    require(sha(args.reset_proof) == value["resetProofSha256"] and sha(args.control_proof) == value["controlProofSha256"], "Reset/control proof changed.")
    if gold:
        require(sha(args.smoke_receipt) == value["smokeReceiptSha256"], "Admitted smoke receipt changed.")
    return value


def run_code(args: argparse.Namespace) -> None:
    from bcal_governed_study import verify_owned_cleanup
    from bcbench_core.agent.experiment import ExperimentConfiguration
    from bcbench_core.exceptions import AgentError, EmptyDiffError
    from bcbench_core.git import commit_changes, init_repo, stage_and_get_diff

    from bcbench.agent.bcal.agent import _read_transcript, _require_completed, _result_metrics, _run_bcal_process

    pin = load_pin()
    pin.verify(args.package, args.archive)
    job = json.loads(args.job.read_bytes())
    gold = job["gold"]
    policy = CodingPolicy(model=job["model"], reasoning_effort="medium", auxiliary="forbid")
    private = args.private
    (private / "auxiliary").mkdir(parents=True, exist_ok=False)
    aggregate = StudyBudget(args.study_budget) if gold else None
    budget = ProviderBudget(args.receipt.with_suffix(".attempts.json"), 64 if gold else 30, (lambda role: aggregate.reserve(job["cell"], role)) if aggregate else None)
    receipt = {"status": "started", "package": pin.model_dump(), "policy": policy.receipt(), "benchCommit": os.environ.get("GITHUB_SHA"), "quality": None, "testPassed": None}
    write_json(args.receipt, receipt)
    started = time.monotonic()
    key = secrets.token_urlsafe(32)
    os.environ["BCAL_REASONING_LOCAL_KEY"] = key
    scenario = private / "scenario.json"
    write_json(scenario, {"schemaVersion": "1.0", "steps": [{"id": "benchmark-prompt" if gold else "synthetic-clamp-priority", "type": "user", "text": job["prompt"]}]})
    workspace = private / "workspace"
    exports = workspace / job.get("project", "smoke") / "src"
    exports.mkdir(parents=True)
    init_repo(workspace)
    commit_changes(workspace, "Initial AL output scaffold", allow_empty=True)
    run = CodingRun(policies=(policy,), max_provider_attempts=64 if gold else 30, timeout_seconds=1230 if gold else 420, page=job["page"], audience=job["audience"])
    process_error = None
    try:
        with provider_route(policy, budget, key) as url:
            command, config = coding_command(args.package, args.symbols, scenario, private, policy, run, url)
            command = [value if not value.startswith("--exportfolder=") else f"--exportfolder={exports}" for value in command]
            with (private / "console.txt").open("w", encoding="utf-8") as console:
                try:
                    _run_bcal_process(command, timeout=1430 if gold else 420, stdout=console, env={**process_environment(), "BCAL_REASONING_LOCAL_KEY": key})
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                    process_error = type(error).__name__
        verify_owned_cleanup(args.package / "bcal.exe")
        receipt["runtimeCleanupVerified"] = True
        transcript = _read_transcript(private / "result.json")
        require(transcript["executionIdentity"]["sourceCommitSha"] == pin.source, "Executed source differs.")
        identity = transcript["runtimeIdentity"]
        require(identity["sdkPackageVersion"] == pin.sdk_package and identity["sdkRuntimeVersion"] == pin.sdk_runtime, "Executed SDK differs.")
        require(identity["mainModel"] == policy.model and identity["reasoningEffort"] == "medium", "Runtime model/effort differs.")
        require(not any((private / "auxiliary").iterdir()), "Forbidden auxiliary invocation.")
        receipt["terminalEvidence"] = transcript_summary(private / "result.json")
        require(
            not budget.stopped and budget.events and all(event.get("httpStatus") == 200 for event in budget.events), "Provider failure or stopped accounting is infrastructure, not a quality score."
        )
        if process_error:
            receipt.update(status="agent-failed", failureCategory=process_error, quality=0.0, testPassed=False)
            return
        experiment = config.experiment(1430 if gold else 420, transcript)
        auxiliary = experiment.execution["auxiliary"]
        experiment = ExperimentConfiguration(execution={**experiment.execution, "auxiliary": {**auxiliary, "completionReviewModel": None}})
        _require_completed(transcript, metrics=_result_metrics(transcript, time.monotonic() - started), config=experiment)
        files = sorted(exports.rglob("*.al"))
        compiled = all(turn.get("compileCoversLatestChange") is True for turn in transcript["agentRuntimeEvidence"])
        safety_empty = gold and job["safety"] and not files
        if gold and not files and not safety_empty:
            receipt.update(status="agent-failed", failureCategory="empty_output", quality=0.0, testPassed=False)
            return
        require(compiled or safety_empty, "Latest source compilation not verified.")
        require(files or safety_empty, "Actual AL export is required.")
        try:
            output = stage_and_get_diff(workspace, exclude=("**/app.json", "*.docx", "*.md"))
        except EmptyDiffError:
            if not (gold and job["safety"]):
                receipt.update(status="agent-failed", failureCategory="empty_output", quality=0.0, testPassed=False)
                return
            output = ""
        if gold:
            write_json(private / "judge-input.json", {"input": job["prompt"], "expected": {"assertions": job["expected"]}, "output": output})
        receipt.update(status="completed", freshCompiled=compiled, exported=True, exportHashes=[sha(path) for path in files])
    except AgentError:
        receipt.update(status="infrastructure-failed", failureCategory="completion_evidence", quality=None, testPassed=None)
    except Exception as error:  # noqa: BLE001 - only safe categories cross the private process boundary
        receipt.update(status="infrastructure-failed", failureCategory=type(error).__name__, quality=None, testPassed=None)
        budget.fail()
    finally:
        try:
            verify_owned_cleanup(args.package / "bcal.exe")
            receipt["runtimeCleanupVerified"] = True
        except Exception:
            receipt["runtimeCleanupVerified"] = False
            if aggregate:
                aggregate.stop()
            raise
        finally:
            receipt["providerAttempts"] = len(budget.events)
            receipt["auxiliaryInvocations"] = len(list((private / "auxiliary").iterdir()))
            receipt["seconds"] = time.monotonic() - started
            receipt["terminalEvidence"] = transcript_summary(private / "result.json")
            receipt["accounting"] = budget.snapshot()
            receipt["cost"] = None
            write_json(args.receipt, receipt)


def run_judge(args: argparse.Namespace) -> None:
    from openai import OpenAI

    job = json.loads(args.job.read_bytes())
    aggregate = StudyBudget(args.study_budget)
    budget = ProviderBudget(args.receipt.with_suffix(".judge-attempts.json"), 1, lambda role: aggregate.reserve(job["cell"], role))
    receipt = json.loads(args.receipt.read_bytes())
    events = []
    key = secrets.token_urlsafe(32)
    try:
        with provider_route(None, budget, key) as url, OpenAI(base_url=url + "/v1", api_key=key, max_retries=0, timeout=90) as client:
            scores = score_checklist(json.loads((args.private / "judge-input.json").read_bytes()), client, events.append)
        require(not budget.stopped and len(budget.events) == 1 and budget.events[0].get("httpStatus") == 200, "Judge accounting is incomplete.")
        receipt.update(status="scored", **scores)
    except Exception as error:  # noqa: BLE001 - infrastructure must remain unscored and expose no raw model data
        budget.fail()
        receipt.update(status="judge-infrastructure-failed", quality=None, testPassed=None, judgeFailureCategory=type(error).__name__)
    finally:
        receipt["judgeDiagnostics"] = events
        receipt["judgeAccounting"] = budget.snapshot()
        write_json(args.receipt, receipt)


def cell_id(index: int, model: str) -> str:
    return f"{index:03d}-{model}"


def execute(args: argparse.Namespace, gold: bool) -> None:
    from bcbench.agent.bcal.agent import _run_bcal_process

    admission = verify_admission(args, gold)
    with (args.output / "execution-once.json").open("x", encoding="utf-8") as file:
        json.dump({"source": os.environ["GITHUB_SHA"], "runId": os.environ["GITHUB_RUN_ID"]}, file)
    entries = frozen_entries() if gold else [{"nl_prompt": TASK, "page": 22, "audience": "Technical", "expected": [], "metadata": {"area": "smoke"}, "instance_id": "synthetic-clamp-priority"}]
    cells = [(cell_id(index, model), row, model) for index, row in enumerate(entries) for model in (MODELS if gold else (MODELS[0],))]
    aggregate = StudyBudget.create(args.output / "study.db", [cell for cell, _, _ in cells], admission["bindingId"]) if gold else None
    package_roots = []
    for worker in range(SEMANTIC_WORKERS if gold else 1):
        destination = args.work / f"worker-{worker}" / "package"
        shutil.copytree(args.package, destination)
        load_pin().verify(destination, args.archive)
        package_roots.append(destination)
    jobs = []
    for cell, entry, model in cells:
        job = args.work / f"{cell}.job.json"
        write_json(
            job,
            {
                "cell": cell,
                "gold": gold,
                "model": model,
                "instanceId": entry["instance_id"],
                "prompt": entry["nl_prompt"],
                "page": entry["page"],
                "audience": entry["audience"],
                "expected": entry["expected"],
                "safety": entry["metadata"]["area"] == "safety",
                "project": entry.get("project_paths", ["smoke"])[0],
            },
        )
        jobs.append((cell, job))

    def command(phase: str, cell: str, job: Path, package: Path) -> list[str]:
        return [
            sys.executable,
            str(Path(__file__).resolve()),
            phase,
            "--package",
            str(package),
            "--archive",
            str(args.archive),
            "--symbols",
            str(args.work / "symbols"),
            "--job",
            str(job),
            "--private",
            str(args.work / cell),
            "--receipt",
            str(args.output / f"{cell}.json"),
            "--study-budget",
            str(args.output / "study.db"),
        ]

    def code_shard(worker: int, judge_pool: ThreadPoolExecutor) -> list[Future]:
        completed = []
        for cell, job in jobs[worker :: len(package_roots)]:
            if aggregate:
                aggregate.admit(cell, admission["bindingId"])
            private = args.work / cell
            private.mkdir()
            with (private / "runner-console.txt").open("w", encoding="utf-8") as console:
                try:
                    _run_bcal_process(command("code", cell, job, package_roots[worker]), timeout=1500 if gold else 480, stdout=console, env=dict(os.environ))
                except Exception:
                    if aggregate:
                        aggregate.stop()
                    raise
            receipt = json.loads((args.output / f"{cell}.json").read_bytes())
            require(receipt.get("runtimeCleanupVerified") is True, "Owned process cleanup unavailable; stop study.")
            require(receipt["providerAttempts"] <= (64 if gold else 30), "Per-cell actual attempt accounting differs.")
            if gold:
                completed.append(judge_pool.submit(judge_cell, cell, job))
        return completed

    def judge_cell(cell: str, job: Path) -> None:
        receipt_path = args.output / f"{cell}.json"
        receipt = json.loads(receipt_path.read_bytes())
        if receipt["status"] != "completed":
            return
        try:
            with (args.work / cell / "judge-console.txt").open("w", encoding="utf-8") as console:
                _run_bcal_process(command("judge", cell, job, args.package), timeout=100, stdout=console, env=dict(os.environ))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            receipt = json.loads(receipt_path.read_bytes())
            receipt.update(status="judge-infrastructure-failed", quality=None, testPassed=None, judgeFailureCategory="judge_process")
            write_json(receipt_path, receipt)

    try:
        with ThreadPoolExecutor(max_workers=JUDGE_WORKERS) as judge_pool, ThreadPoolExecutor(max_workers=len(package_roots)) as coding_pool:
            pending = [coding_pool.submit(code_shard, worker, judge_pool) for worker in range(len(package_roots))]
            judgments = []
            for future in as_completed(pending):
                judgments.extend(future.result())
            for future in judgments:
                future.result()
    finally:
        rows = []
        for cell, entry, model in cells:
            path = args.output / f"{cell}.json"
            rows.append(
                {
                    "cell": cell,
                    "instanceId": entry["instance_id"],
                    "model": model,
                    "receiptSha256": sha(path) if path.is_file() else None,
                    "status": json.loads(path.read_bytes())["status"] if path.is_file() else "no-terminal-receipt",
                }
            )
        write_json(
            args.output / "summary.json",
            {"binding": admission["binding"], "package": admission["package"], "cells": rows, "accounting": aggregate.snapshot() if aggregate else None, "retries": 0, "repetitions": 1, "gold": gold},
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("admit-smoke", "smoke", "admit-gold", "gold", "code", "judge"))
    for name in ("package", "archive"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("work", "output", "symbol-cache", "helper", "reset-proof", "control-proof", "smoke-receipt", "symbols", "job", "private", "receipt", "study-budget"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    try:
        if args.phase.startswith("admit-"):
            admit(args)
        elif args.phase in ("smoke", "gold"):
            execute(args, args.phase == "gold")
        else:
            {"code": run_code, "judge": run_judge}[args.phase](args)
    except Exception as error:  # noqa: BLE001 - no prompts, credentials, source or provider text in public logs
        sys.stderr.write(f"Opt-in reasoning evaluation stopped: {type(error).__name__}\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
