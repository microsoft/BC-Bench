import importlib
import json
import subprocess
import sys
from argparse import Namespace
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
evaluation = importlib.import_module("bcal_reasoning_evaluation")
package = importlib.import_module("bcal_reasoning_package")


def pin():
    return package.PackagePin(version="30.0.46.99999-beta", source="c" * 40, archive_sha256="a" * 64, runtime_files=224, sdk_package="1.0.29", sdk_runtime="1.0.107")


def test_frozen_gold_selection_is_exactly_110_cases_and_330_unique_cells():
    entries = evaluation.frozen_entries()
    assert len(entries) == 110
    assert len({evaluation.cell_id(index, model) for index in range(110) for model in evaluation.MODELS}) == 330


@pytest.mark.parametrize("damage", ["wrong-package", "not-delivered", "auxiliary", "callback-fence"])
def test_package_control_gate_rejects_mismatched_or_failed_proof(tmp_path, damage):
    p = pin().model_dump()
    proof = {
        "identity": {"kind": "exact-governed-package", "version": p["version"], "source": p["source"], "archiveSha256": p["archive_sha256"], "verifiedRuntimeFiles": p["runtime_files"]},
        "forcedTool": "start_new_work",
        "providerAttempts": 0,
        "offlineRequests": 2,
        "secondRequestContainsToolResult": True,
        "packagePayloadUnchanged": True,
        "auxiliaryInvocations": 0,
        "terminalEvidence": {"failureMessageSignature": "unknown"},
    }
    if damage == "wrong-package":
        proof["identity"]["source"] = "b" * 40
    elif damage == "not-delivered":
        proof["secondRequestContainsToolResult"] = False
    elif damage == "auxiliary":
        proof["auxiliaryInvocations"] = 1
    else:
        proof["terminalEvidence"]["failureMessageSignature"] = "callback_fence_guard"
    path = tmp_path / "proof.json"
    path.write_text(json.dumps(proof))
    with pytest.raises(evaluation.AdmissionError):
        evaluation.validate_tool_proof(path, p, "start_new_work")


@pytest.mark.parametrize("failure", [None, "process", "http429", "identity", "auxiliary", "stale", "safety-empty", "empty-output"])
def test_new_package_coding_uses_actual_cli_and_keeps_infrastructure_unscored(tmp_path, monkeypatch, failure):
    import bcal_governed_study

    from bcbench.agent.bcal import agent

    p = pin()
    monkeypatch.setattr(evaluation, "load_pin", lambda: p)
    monkeypatch.setattr(package.PackagePin, "verify", lambda *args: 224)
    monkeypatch.setattr(bcal_governed_study, "verify_owned_cleanup", lambda *args: None)
    monkeypatch.setattr(agent, "_require_completed", lambda *args, **kwargs: None)

    @contextmanager
    def route(policy, budget, key):
        budget.send("main", {"model": policy.model, "reasoning": {"effort": "medium"}}, lambda: SimpleNamespace(status_code=429 if failure == "http429" else 200))
        yield "http://127.0.0.1:1234"

    monkeypatch.setattr(evaluation, "provider_route", route)
    private = tmp_path / "private"
    private.mkdir()
    gold = failure in ("safety-empty", "empty-output")
    study = evaluation.StudyBudget.create(tmp_path / "study.db", [f"cell-{i}" for i in range(330)], "binding")
    study.admit("cell-0", "binding")
    job = tmp_path / "job.json"
    job.write_text(
        json.dumps({"cell": "cell-0", "gold": gold, "model": evaluation.MODELS[0], "prompt": "PRIVATE", "page": 22, "audience": "Both", "safety": failure == "safety-empty", "expected": []})
    )
    args = Namespace(package=tmp_path, archive=tmp_path / "archive", job=job, private=private, receipt=tmp_path / "receipt.json", symbols=tmp_path / "symbols", study_budget=study.path)

    def run(command, **kwargs):
        assert command[0] == str(tmp_path / "bcal.exe")
        assert "--sdk-reasoning-effort=medium" in command
        assert ("--sdk-max-model-requests=64" if gold else "--sdk-max-model-requests=30") in command
        assert "--audience=Both" in command
        assert not any(value.startswith("--server") for value in command)
        assert not any(name.startswith("LLM_API_") for name in kwargs["env"])
        transcript = {
            "schemaVersion": "1.1",
            "executionIdentity": {"sourceCommitSha": "wrong" if failure == "identity" else p.source},
            "runtimeIdentity": {"sdkPackageVersion": p.sdk_package, "sdkRuntimeVersion": p.sdk_runtime, "mainModel": evaluation.MODELS[0], "reasoningEffort": "medium"},
            "agentRuntimeEvidence": [{"compileCoversLatestChange": failure not in ("stale", "safety-empty")}],
        }
        (private / "result.json").write_text(json.dumps(transcript))
        target = next(value.removeprefix("--exportfolder=") for value in command if value.startswith("--exportfolder="))
        if not gold:
            (Path(target) / "Synthetic.al").write_text("codeunit 50149 Synthetic {}")
        if failure == "auxiliary":
            (private / "auxiliary" / "forbidden.json").write_text("{}")
        if failure == "process":
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(agent, "_run_bcal_process", run)
    evaluation.run_code(args)
    receipt = json.loads(args.receipt.read_bytes())
    assert receipt["providerAttempts"] == 1
    assert receipt["runtimeCleanupVerified"]
    assert "PRIVATE" not in json.dumps(receipt)
    if failure in ("process", "empty-output"):
        assert receipt["status"] == "agent-failed"
        assert receipt["quality"] == 0
    elif failure and not gold:
        assert receipt["status"] == "infrastructure-failed"
        assert receipt["quality"] is None
        assert receipt["testPassed"] is None
    else:
        assert receipt["status"] == "completed"
        assert receipt["freshCompiled"] is not gold
        assert receipt["exported"]
        assert receipt["quality"] is None
        if gold:
            assert json.loads((private / "judge-input.json").read_bytes())["output"] == ""


def test_single_execution_marker_cannot_be_replaced(tmp_path, monkeypatch):
    output = tmp_path / "safe"
    output.mkdir()
    (output / "execution-once.json").write_text('{"source":"preserved"}')
    monkeypatch.setattr(evaluation, "verify_admission", lambda *args: {})
    args = Namespace(output=output)
    with pytest.raises(FileExistsError):
        evaluation.execute(args, False)
    assert (output / "execution-once.json").read_text() == '{"source":"preserved"}'


def test_frozen_gold_orchestration_admits_each_cell_once_and_streams_bounded_judging(tmp_path, monkeypatch):
    from bcbench.agent.bcal import agent

    output = tmp_path / "safe"
    output.mkdir()
    work = tmp_path / "private"
    work.mkdir()
    package_root = tmp_path / "package"
    package_root.mkdir()
    monkeypatch.setenv("GITHUB_SHA", "source")
    monkeypatch.setenv("GITHUB_RUN_ID", "offline")
    monkeypatch.setattr(evaluation, "verify_admission", lambda *args: {"bindingId": "binding", "binding": {}, "package": {}})
    monkeypatch.setattr(evaluation, "load_pin", lambda: SimpleNamespace(verify=lambda *args: None))
    monkeypatch.setattr(
        evaluation,
        "frozen_entries",
        lambda: [{"instance_id": f"case-{index}", "nl_prompt": "PRIVATE", "expected": [], "page": 22, "audience": "Both", "metadata": {"area": "smoke"}} for index in range(110)],
    )
    calls = {"code": set(), "judge": set()}
    lock = Lock()
    judge_started = Event()

    def run(command, **kwargs):
        phase = command[2]
        options = dict(zip(command[3::2], command[4::2], strict=True))
        job = json.loads(Path(options["--job"]).read_bytes())
        cell = job["cell"]
        with lock:
            assert cell not in calls[phase]
            calls[phase].add(cell)
            code_count = len(calls["code"])
        study = evaluation.StudyBudget(Path(options["--study-budget"]))
        study.reserve(cell, "main" if phase == "code" else "judge")
        path = Path(options["--receipt"])
        if phase == "code":
            path.write_text('{"status":"completed","runtimeCleanupVerified":true,"providerAttempts":1,"quality":null}')
            if code_count == 5:
                assert judge_started.wait(5), "Judges were delayed until coding shards completed."
        else:
            judge_started.set()
            receipt = json.loads(path.read_bytes())
            receipt.update(status="scored", quality=1.0, testPassed=True)
            path.write_text(json.dumps(receipt))

    monkeypatch.setattr(agent, "_run_bcal_process", run)
    args = Namespace(work=work, output=output, package=package_root, archive=tmp_path / "archive")
    evaluation.execute(args, True)
    summary = json.loads((output / "summary.json").read_bytes())
    assert len(summary["cells"]) == 330
    assert {row["status"] for row in summary["cells"]} == {"scored"}
    assert len(calls["code"]) == len(calls["judge"]) == summary["accounting"]["admittedCells"] == 330
    assert summary["accounting"]["codingAttempts"] == summary["accounting"]["judgeAttempts"] == 330
    assert summary["accounting"]["attempts"] == 660
    assert summary["repetitions"] == 1
    assert summary["retries"] == 0
    assert "PRIVATE" not in json.dumps(summary)


def test_judge429_remains_null_and_preserves_attempts_without_rejudging(tmp_path, monkeypatch):
    study = evaluation.StudyBudget.create(tmp_path / "study.db", [f"cell-{i}" for i in range(330)], "binding")
    study.admit("cell-0", "binding")
    job = tmp_path / "job.json"
    job.write_text('{"cell":"cell-0"}')
    (tmp_path / "judge-input.json").write_text('{"expected":{"assertions":[]}}')
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text('{"status":"completed","quality":null,"testPassed":null}')

    @contextmanager
    def route(policy, budget, key):
        budget.send("judge", {"model": "gpt-56-ceres"}, lambda: SimpleNamespace(status_code=429))
        raise evaluation.AdmissionError("Synthetic judge failure")
        yield  # pragma: no cover

    monkeypatch.setattr(evaluation, "provider_route", route)
    args = Namespace(job=job, study_budget=study.path, private=tmp_path, receipt=receipt_path)
    evaluation.run_judge(args)
    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["status"] == "judge-infrastructure-failed"
    assert receipt["quality"] is None
    assert receipt["testPassed"] is None
    assert receipt["judgeAccounting"]["attempts"] == study.snapshot()["judgeAttempts"] == 1
