import importlib.util
import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("judge_study_test", ROOT / "scripts" / "bcal_governed_study.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)
transport_spec = importlib.util.spec_from_file_location("judge_transport_test", ROOT / "scripts" / "bcal_study_transport.py")
transport = importlib.util.module_from_spec(transport_spec)
transport_spec.loader.exec_module(transport)


@pytest.mark.parametrize("failure", ["http_status", "transport", "timeout", "json_decode", "response_validation", "checklist_incomplete", "output_failure", "negative", "success"])
def test_actual_pinned_judge_subprocess_retains_safe_failure_boundaries(tmp_path, failure):
    python = os.environ.get("BCAL_OFFLINE_JUDGE_PYTHON", sys.executable)
    probe = subprocess.run([python, "-c", "import autoevals,bc_eval,openai,httpx2"], capture_output=True, check=False)
    if probe.returncode:
        pytest.skip("Pinned judge environment required; set BCAL_OFFLINE_JUDGE_PYTHON")
    private = "PRIVATE PROMPT RESPONSE SECRET"
    job = {"input": private, "output": private, "expected": {"assertions": [{"text": private, "level": "expected"}]}}
    study.write_json(tmp_path / "judge-input.json", job)
    if failure == "output_failure":
        (tmp_path / "judge-output.json").mkdir()
    launcher = """
import json, os, runpy, socket, sys
from pathlib import Path
import httpx2 as httpx
import openai
def forbidden(*args, **kwargs):
    raise AssertionError("Network forbidden")
socket.socket.connect = socket.socket.connect_ex = socket.getaddrinfo = forbidden
calls = []
def respond(request):
    calls.append(request)
    assert len(calls) == 1
    body = json.loads(request.content)
    assert body["model"] == "gpt-56-ceres"
    assert body["max_completion_tokens"] == 4096
    assert body["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in body
    failure = os.environ["TEST_FAILURE"]
    if failure == "transport":
        raise httpx.ReadError("PRIVATE", request=request)
    if failure == "timeout":
        raise httpx.ReadTimeout("PRIVATE", request=request)
    if failure == "http_status":
        return httpx.Response(503, json={"error":{"message":"PRIVATE"}}, headers={"x-request-id":"PRIVATE"})
    if failure == "response_validation":
        return httpx.Response(200, json={"choices":[]})
    content = "{" if failure == "json_decode" else json.dumps({"assertions":[] if failure == "checklist_incomplete" else [{"text":"PRIVATE PROMPT RESPONSE SECRET","pass":failure != "negative","reasoning":"PRIVATE"}]})
    return httpx.Response(200, json={"id":"offline","object":"chat.completion","created":0,"model":"gpt-56-ceres","choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":content}}]})
real_client = openai.OpenAI
def client(**kwargs):
    assert kwargs["max_retries"] == 0
    return real_client(**kwargs,http_client=httpx.Client(transport=httpx.MockTransport(respond)))
openai.OpenAI = client
sys.argv = [sys.argv[1],"judge","--input",sys.argv[2],"--output",sys.argv[3]]
try:
    runpy.run_path(sys.argv[0],run_name="__main__")
finally:
    Path(os.environ["TEST_CALL_COUNT"]).write_text(str(len(calls)))
"""
    result = subprocess.run(
        [python, "-c", launcher, str(ROOT / "scripts" / "bcal_study_transport.py"), str(tmp_path / "judge-input.json"), str(tmp_path / "judge-output.json")],
        capture_output=True,
        check=False,
        text=True,
        env={**os.environ, "TEST_FAILURE": failure, "TEST_CALL_COUNT": str(tmp_path / "call-count"), "BCAL_STUDY_CHAT_URL": "https://offline.invalid", "BCAL_SDK_PROXY_KEY": private},
        timeout=30,
    )
    assert result.returncode == (0 if failure in ("success", "negative") else 1), result.stderr
    assert (tmp_path / "call-count").read_text() == "1"
    safe = study.legacy_diagnostic_receipt(tmp_path / "judge-output.diagnostics.json")
    assert safe["valid"] is True
    assert private not in json.dumps(safe)
    assert "PRIVATE" not in result.stdout + result.stderr
    if failure in ("success", "negative"):
        assert safe["events"][-1]["outcome"] == "emitted"
        passed = failure == "success"
        assert json.loads((tmp_path / "judge-output.json").read_bytes()) == {"quality": float(passed), "testPassed": passed, "assertionPass": [passed]}
    else:
        assert not (tmp_path / "judge-output.json").is_file()
        assert any(event.get("category") == ("command_io" if failure == "output_failure" else failure) for event in safe["events"])
        if failure == "http_status":
            assert any(event.get("httpStatus") == 503 for event in safe["events"])


@pytest.mark.parametrize("failure", ["command_exit", "process_timeout", "malformed_output"])
def test_parent_judge_failure_bubbles_with_process_receipt_and_preserves_exception(tmp_path, monkeypatch, capsys, failure):
    from bcbench.agent.bcal import agent

    error = subprocess.CalledProcessError(7, ["PRIVATE"]) if failure == "command_exit" else subprocess.TimeoutExpired(["PRIVATE"], 100)

    def run(*args, **kwargs):
        study.write_json(
            tmp_path / "judge-output.diagnostics.json", {"schemaVersion": 1, "events": [{"phase": "client", "outcome": "failed", "category": "http_status", "httpStatus": 503, "message": "PRIVATE"}]}
        )
        study.write_json(
            tmp_path / "Judge-chat-completions.audit.diagnostics.json", {"schemaVersion": 1, "events": [{"phase": "headers", "outcome": "received", "httpStatus": 503, "authorization": "PRIVATE"}]}
        )
        if failure == "malformed_output":
            (tmp_path / "judge-output.json").write_text("{")
            return
        raise error

    monkeypatch.setattr(agent, "_run_bcal_process", run)
    attempt = {"quality": None}
    with pytest.raises(json.JSONDecodeError if failure == "malformed_output" else type(error)) as caught:
        study.run_judge(["PRIVATE"], tmp_path, {}, attempt)
    if failure != "malformed_output":
        assert caught.value is error
    diagnostic = attempt["judgeDiagnostics"]
    assert diagnostic["process"]["exitCode"] == (7 if failure == "command_exit" else 0 if failure == "malformed_output" else None)
    assert diagnostic["process"]["failureCategory"] == {"command_exit": "command_exit", "process_timeout": "timeout", "malformed_output": "response_json"}[failure]
    assert diagnostic["client"]["events"][0]["httpStatus"] == diagnostic["transport"]["events"][0]["httpStatus"] == 503
    assert attempt["quality"] is None
    assert "PRIVATE" not in json.dumps(diagnostic) + capsys.readouterr().err


@pytest.mark.parametrize("assertions", [[], [{"text": "PRIVATE", "pass": "false"}], [{"text": "PRIVATE", "pass": True}, {"text": "PRIVATE", "pass": True}], [{"text": "WRONG", "pass": True}]])
def test_missing_duplicate_or_invalid_assertions_are_unknown_not_quality_zero(assertions):
    events = []
    encoded = json.dumps({"choices": [{"message": {"content": json.dumps({"assertions": assertions})}}]})
    with pytest.raises(ValueError, match="complete checklist"):
        transport.validate_judge_response(encoded, [{"text": "PRIVATE"}], events.append)
    assert events == [{"phase": "validation", "outcome": "failed", "category": "checklist_incomplete"}]
    assert "PRIVATE" not in json.dumps(events)


def test_transport_retains_only_numeric_retry_after_and_hashed_request_id():
    httpx = pytest.importorskip("httpx2")
    events = []
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(429, content=b"PRIVATE", headers={"x-request-id": "PRIVATE", "retry-after": "12"}))) as client,
        transport.forward_response(client, client.build_request("POST", "https://offline.invalid"), RuntimeError, events.append) as response,
    ):
        response.read()
    assert events[0]["httpStatus"] == 429
    assert events[0]["retryAfterSeconds"] == 12
    assert len(events[0]["requestIdSha256"]) == 64
    assert "PRIVATE" not in json.dumps(events)


@pytest.mark.parametrize("failure", ["command_exit", "process_timeout"])
def test_real_parent_subprocess_failure_retains_exit_and_timeout(tmp_path, monkeypatch, failure):
    from bcbench.agent.bcal import agent

    run = agent._run_bcal_process
    monkeypatch.setattr(agent, "_run_bcal_process", lambda command, **kwargs: run(command, **{**kwargs, "timeout": 0.5}))
    command = [sys.executable, "-c", "import sys,time;time.sleep(30)" if failure == "process_timeout" else "import sys;sys.exit(7)"]
    attempt = {"quality": None}
    with pytest.raises(subprocess.TimeoutExpired if failure == "process_timeout" else subprocess.CalledProcessError):
        study.run_judge(command, tmp_path, os.environ.copy(), attempt)
    assert attempt["judgeFailed"] is True
    assert attempt["judgeDiagnostics"]["process"]["failureCategory"] == ("timeout" if failure == "process_timeout" else "command_exit")
    assert attempt["judgeDiagnostics"]["client"]["available"] is False
    assert attempt["quality"] is None


def test_new_comparison_selects_exactly_220_frozen_counterbalanced_slots(monkeypatch):
    monkeypatch.setattr(study, "INPUTS", ROOT / "experiments" / "bcal-full-gold-judge-diagnostics")
    selected = study.pairs()
    assert len(selected) == 110
    assert len({pair["instanceId"] for pair in selected}) == 110
    assert sum(len(pair["order"]) for pair in selected) == 220
    assert sum(pair["order"][0] == "legacy" for pair in selected) == 55
    assert all(pair["repeat"] == 1 and set(pair["order"]) == {"legacy", "copilot-sdk"} for pair in selected)
    assert study.study()["inference"]["reasoning"] == "none"


@pytest.mark.parametrize("mutation", [{"caseCount": 111}, {"variants": ["legacy"]}, {"judge": {"model": "different"}}, {"comparisonOf": {}}])
def test_new_comparison_rejects_workload_or_history_mutation(tmp_path, monkeypatch, mutation):
    manifest = json.loads((ROOT / "experiments" / "bcal-full-gold-judge-diagnostics" / "study.json").read_bytes())
    study.write_json(tmp_path / "study.json", {**manifest, **mutation})
    monkeypatch.setattr(study, "INPUTS", tmp_path)
    with pytest.raises(ValueError, match="selectors and scoring"):
        study.study_manifest()


def test_new_pair_runs_other_authorized_slot_after_judge_failure_then_fails(tmp_path, monkeypatch):
    config = {"studyId": "bcal-full-gold-judge-diagnostics-comparison1", "cohort": "full-gold-paired-v1", "historicalAccounting": {}, "pairTimeoutSeconds": 3900}
    pair = {"index": 0, "order": ["legacy", "copilot-sdk"]}
    monkeypatch.setattr(study, "study", lambda: config)
    monkeypatch.setattr(study, "pairs", lambda: [pair])
    for name in ("verify_runtime_diagnostics_proof", "verify_runtime_effort_proof", "verify_judge_diagnostics_proof", "prepare_package", "verify_symbols"):
        monkeypatch.setattr(study, name, lambda *args: None)
    calls = []

    def attempt(pair, runtime, work, env, output):
        calls.append(runtime)
        row = {"status": "judge-failed" if runtime == "legacy" else "judged", "cleanupVerified": True}
        study.write_json(output, row)
        return row

    monkeypatch.setattr(study, "run_attempt", attempt)
    with pytest.raises(ValueError, match="both authorized runtime slots attempted"):
        study.run_pair(Namespace(pair=0, work=tmp_path / "private", output=tmp_path / "public"))
    assert calls == ["legacy", "copilot-sdk"]
    receipt = json.loads((tmp_path / "public" / "pair-0.json").read_bytes())
    assert receipt["status"] == "incomplete"
    assert receipt["admitted"] == calls
