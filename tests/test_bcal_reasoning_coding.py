import importlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
coding = importlib.import_module("bcal_reasoning_coding")
MODELS = ("gpt-56-reasoning-sol", "gpt-56-ceres", "gpt-55-chat")


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("policy", ["none", "medium", "unset"])
def test_model_policy_reaches_actual_bcal_cli_without_unset_fallback(tmp_path, monkeypatch, model, policy):
    monkeypatch.setenv("BCAL_REASONING_LOCAL_KEY", "local-only")
    selected = coding.CodingPolicy(model=model, reasoning_effort=policy, auxiliary="forbid")
    run = coding.CodingRun(policies=[selected], max_provider_attempts=8, timeout_seconds=120, page=22)
    command, config = coding.coding_command(tmp_path, tmp_path, tmp_path / "scenario.json", tmp_path, selected, run, "http://127.0.0.1:1234")
    assert command[0] == str(tmp_path / "bcal.exe")
    assert f"--sdk-model={model}" in command
    assert "--agent-runtime=copilot-sdk" in command
    assert "--agent-planning=copilot" in command
    assert [value for value in command if value.startswith("--sdk-reasoning-effort=")] == ([] if policy == "unset" else [f"--sdk-reasoning-effort={policy}"])
    assert config.sdk_reasoning_effort == (None if policy == "unset" else policy)
    assert selected.receipt()["expectedWireEffort"] == {"presence": "explicit", "value": "medium" if policy == "unset" else policy}
    assert "local-only" not in json.dumps(command)
    assert "forbid-auxiliary" in config.command


@pytest.mark.parametrize("mutation", [{"reasoning_effort": None}, {"reasoning_effort": "high"}, {"reasoning_effort": "None"}, {"model": "sol"}, {"auxiliary": "same-as-main"}, {"fallback": "none"}])
def test_unsupported_policy_is_explicit_local_rejection(mutation):
    with pytest.raises(ValidationError):
        coding.CodingPolicy.model_validate({"model": MODELS[0], "reasoning_effort": "medium", "auxiliary": "forbid", **mutation})


@pytest.mark.parametrize(
    "body",
    [
        {"model": coding.MODELS[0], "reasoning": None},
        {"model": coding.MODELS[0]},
        {"model": coding.MODELS[0], "reasoning": {"effort": "none"}},
        {"model": coding.MODELS[1], "reasoning": {"effort": "medium"}},
        {"model": coding.MODELS[0], "reasoning": {"effort": "medium"}, "reasoning_effort": "medium"},
    ],
)
def test_native_unset_requires_pinned_generated_medium_not_omission_or_null(body):
    selected = coding.CodingPolicy(model=coding.MODELS[0], reasoning_effort="unset", auxiliary="forbid")
    with pytest.raises(coding.AdmissionError):
        selected.verify_wire({**body, "parallel_tool_calls": False})
    selected.verify_wire({"model": coding.MODELS[0], "reasoning": {"effort": "medium", "summary": "auto"}, "parallel_tool_calls": False})


def test_pre_send_cap_persists_and_serializes_actual_attempts(tmp_path):
    budget = coding.ProviderBudget(tmp_path / "attempts.json", 3)
    sent = []

    def send(index):
        def operation():
            saved = json.loads(budget.path.read_bytes())
            assert saved["events"][-1]["outcome"] == "reserved"
            sent.append(index)
            return SimpleNamespace(status_code=200)

        try:
            budget.send("main", {"model": coding.MODELS[0], "input": index}, operation)
        except coding.AdmissionError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(send, range(10))) == 3
    assert len(sent) == budget.snapshot()["attempts"] == 3
    assert budget.snapshot()["stopped"]
    with pytest.raises(FileExistsError):
        coding.ProviderBudget(budget.path, 3)


@pytest.mark.parametrize("status", [400, 429, 503, "transport"])
def test_any_failed_send_stops_other_models_and_roles_before_retry(tmp_path, status):
    budget = coding.ProviderBudget(tmp_path / "attempts.json", 20)
    sent = []

    def operation():
        sent.append(True)
        if status == "transport":
            raise ConnectionError("PRIVATE")
        return SimpleNamespace(status_code=status)

    if status == "transport":
        with pytest.raises(ConnectionError):
            budget.send("main", {"model": coding.MODELS[0]}, operation)
    else:
        budget.send("main", {"model": coding.MODELS[0]}, operation)
    with pytest.raises(coding.AdmissionError):
        budget.send("judge", {"model": coding.MODELS[1]}, operation)
    assert budget.snapshot()["attempts"] == len(sent) == 1
    assert "PRIVATE" not in budget.path.read_text()


def test_identical_request_retry_is_not_new_coding_turn(tmp_path):
    budget = coding.ProviderBudget(tmp_path / "attempts.json", 20)
    body = {"model": coding.MODELS[0], "reasoning": {"effort": "medium"}}
    budget.send("main", body, lambda: SimpleNamespace(status_code=200))
    with pytest.raises(coding.AdmissionError):
        budget.send("main", body, lambda: pytest.fail("Retry reached actual send"))
    assert budget.snapshot()["attempts"] == 1


def test_stream_observation_retains_usage_and_reasoning_availability_not_content(tmp_path):
    httpx = pytest.importorskip("httpx2")
    budget = coding.ProviderBudget(tmp_path / "attempts.json", 30)
    budget.send("main", {"model": MODELS[0]}, lambda: SimpleNamespace(status_code=200))
    payload = {
        "type": "response.completed",
        "response": {
            "model": "safe-model",
            "status": "completed",
            "output": [{"type": "message", "content": "PRIVATE"}],
            "usage": {"input_tokens": 10, "output_tokens": 4, "output_tokens_details": {"reasoning_tokens": 2}},
        },
    }
    data = ("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n").encode()
    observed = coding.ObservedResponse(httpx.Response(200, content=data), budget, True)
    assert b"".join(observed.iter_bytes()) == data
    result = budget.events[0]["response"]
    assert observed.completed
    assert not budget.stopped
    assert result["usage"] == {"input_tokens": 10, "output_tokens": 4}
    assert result["reasoningTokensAvailable"]
    assert result["reasoningTokens"] == 2
    assert "PRIVATE" not in budget.path.read_text()


@pytest.mark.parametrize("known", [True, False])
def test_terminal_diagnostics_allowlist_state_and_counters_without_raw_failure(tmp_path, known):
    path = tmp_path / "result.json"
    path.write_text(
        json.dumps(
            {
                "failure": {"code": "turn_failed" if known else "PRIVATE_CODE", "message": "PRIVATE_CREDENTIAL_PROMPT"},
                "agentRuntimeEvidence": [
                    {
                        "terminalState": "protocol-error" if known else "PRIVATE_STATE",
                        "modelRequests": 1,
                        "toolCalls": 0,
                        "responseIterations": 1,
                        "domainCompleted": False,
                        "mutationSucceeded": False,
                        "reasoningTokens": 101,
                        "inputTokens": "PRIVATE",
                        "outputTokens": -1,
                        "unknownField": "PRIVATE",
                    }
                ],
            }
        )
    )
    summary = coding.transcript_summary(path)
    assert summary["failureCode"] == ("turn_failed" if known else "unknown")
    assert summary["turns"] == [
        {
            "terminalState": "protocol-error" if known else "unknown",
            "modelRequests": 1,
            "toolCalls": 0,
            "responseIterations": 1,
            "domainCompleted": False,
            "mutationSucceeded": False,
            "reasoningTokens": 101,
        }
    ]
    assert "PRIVATE" not in json.dumps(summary)


@pytest.mark.parametrize("suffix", ["", " PRIVATE", "\n"])
def test_failure_signature_requires_exact_full_source_constant(tmp_path, suffix):
    path = tmp_path / "result.json"
    path.write_text(
        json.dumps(
            {
                "failure": {
                    "code": "turn_failed",
                    "message": "Native planning tool arguments were absent." + suffix,
                }
            }
        )
    )
    summary = coding.transcript_summary(path)
    assert summary["failureMessageSignature"] == ("missing_native_args" if not suffix else "unknown")
    assert "Native planning" not in json.dumps(summary)
    assert "PRIVATE" not in json.dumps(summary)


@pytest.mark.parametrize(
    ("failure", "shared"), [(failure, shared) for failure in ("429", "redirect", "wire", "model", "duplicate", "authentication") for shared in (False, True)] + [("aggregate", True)]
)
def test_actual_loopback_handler_and_innermost_boundary_fail_closed(tmp_path, monkeypatch, failure, shared):
    from bcal_reasoning_budget import StudyBudget

    httpx = pytest.importorskip("httpx2")
    identity = pytest.importorskip("azure.identity")
    llm_api = pytest.importorskip("bc_eval.llm.llm_api")
    policy = coding.CodingPolicy(model=MODELS[0], reasoning_effort="medium", auxiliary="forbid")
    study = StudyBudget.create(tmp_path / "study.db", [f"cell-{i}" for i in range(330)], "binding") if shared else None
    if study:
        study.admit("cell-0", "binding")
        if failure == "aggregate":
            for _ in range(64):
                study.reserve("cell-0", "main")
    budget = coding.ProviderBudget(tmp_path / "attempts.json", 10, (lambda role: study.reserve("cell-0", role)) if study else None)
    sent = []

    def respond(request):
        assert json.loads(budget.path.read_bytes())["attempts"] == len(sent) + 1
        if study:
            assert study.snapshot()["codingAttempts"] == len(sent) + 1
        assert request.headers["authorization"] == "Bearer PRIVATE"
        sent.append(True)
        return httpx.Response(429 if failure == "429" else 302 if failure == "redirect" else 200, json={"status": "completed", "output": []})

    @contextmanager
    def credential(*args, **kwargs):
        yield object()

    def token():
        if failure == "authentication":
            from azure.core.exceptions import ClientAuthenticationError

            raise ClientAuthenticationError("PRIVATE")
        return "PRIVATE"

    monkeypatch.setattr(identity, "CertificateCredential", credential)
    monkeypatch.setattr(identity, "get_bearer_token_provider", lambda *args: token)
    monkeypatch.setattr(llm_api.LlmApiSettings, "from_env", lambda: SimpleNamespace(environment="TEST", tenant_id="local", client_id="local"))
    monkeypatch.setattr(llm_api, "LlmApiTransport", lambda settings, inner: inner)
    monkeypatch.setattr(llm_api, "taxonomy_headers", lambda *args, **kwargs: {"X-ModelType": "dev-" + policy.model, "x-llm-models": "dev-" + policy.model})
    monkeypatch.setattr(httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(respond))
    monkeypatch.setenv("LLM_API_CERTIFICATE_FILE", "not-a-certificate")

    def post(url, body):
        request = urllib.request.Request(url + "/v1/responses", data=json.dumps(body).encode(), headers={"Authorization": "Bearer local"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
                return response.status
        except urllib.error.HTTPError as error:
            error.read()
            return error.code

    body = {"model": policy.model, "reasoning": {"effort": "none" if failure == "wire" else "medium"}, "parallel_tool_calls": False}
    if failure == "model":
        body["model"] = MODELS[1]
    with coding.provider_route(policy, budget, "local") as url:
        status = post(url, body)
        assert status == {"429": 429, "redirect": 302, "wire": 502, "model": 400, "duplicate": 200, "aggregate": 502, "authentication": 502}[failure]
        assert post(url, {**body, "reasoning": {"effort": "medium"}}) in (400, 502)
    assert len(sent) == budget.snapshot()["attempts"] == (0 if failure in ("wire", "model", "aggregate", "authentication") else 1)
    assert budget.snapshot()["routeStages"]["local_post"] == 2
    if failure == "authentication":
        assert budget.snapshot()["routeStages"]["authentication_started"] == 2
        assert "authentication_completed" not in budget.snapshot()["routeStages"]
        assert budget.snapshot()["routeFailure"] == {"stage": "proxy_error", "httpStatus": 502, "exceptionCategory": "authentication"}
    if study:
        assert study.snapshot()["codingAttempts"] == (64 if failure == "aggregate" else len(sent))
    assert budget.stopped
    assert "PRIVATE" not in budget.path.read_text()


def test_child_environment_excludes_runtime_overrides_and_connection_secrets(monkeypatch):
    for key in ["BCAL_SDK_REASONING_EFFORT", "BCAL_COMPLETION_REVIEW_MODEL", "OPENAI_API_KEY", "LLM_API_CERTIFICATE_FILE", "BC_SERVER_URL", "AZURE_CLIENT_SECRET", "GITHUB_TOKEN"]:
        monkeypatch.setenv(key, "PRIVATE")
    result = coding.process_environment()
    assert "PRIVATE" not in json.dumps(result)
    assert not any(key.startswith("BCAL_") for key in result)


def test_forbidden_auxiliary_command_is_runnable_in_actual_sanitized_environment():
    coding.verify_auxiliary_command(coding.process_environment())


def test_auxiliary_is_recorded_failure_not_fake_response(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "bcal_reasoning_coding.py"), "forbid-auxiliary", "--output", str(tmp_path)],
        input="PRIVATE",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "PRIVATE" not in result.stderr
    assert json.loads(next(tmp_path.glob("*.json")).read_bytes()) == {"role": "auxiliary", "outcome": "forbidden", "providerAttempts": 0}


@pytest.mark.parametrize("failure", [None, "process", "auxiliary", "source", "compile", "empty-export"])
def test_coding_entrypoint_uses_full_packaged_scenario_and_completion_guards(tmp_path, monkeypatch, failure):
    from bcbench.agent.bcal import agent

    monkeypatch.setenv("BCAL_COMPLETION_REVIEW_MODEL", "must-not-inherit")
    selected = coding.CodingPolicy(model=coding.MODELS[0], reasoning_effort="medium", auxiliary="forbid")
    config = coding.CodingRun(policies=[selected], max_provider_attempts=4, timeout_seconds=120, page=22)
    (tmp_path / "config.json").write_text(config.model_dump_json())
    (tmp_path / "scenario.json").write_text(json.dumps({"schemaVersion": "1.0", "steps": [{"id": "coding", "type": "user", "text": "Implement synthetic AL and compile."}]}))
    symbols = tmp_path / "symbols"
    symbols.mkdir()
    (symbols / "fixture.app").write_bytes(b"synthetic symbols")
    monkeypatch.setattr(coding, "verify_package", lambda *args: 224)
    monkeypatch.setattr(coding, "PACKAGE_SOURCE", "synthetic-source")

    @contextmanager
    def route(policy, budget, key):
        budget.send("main", {"model": policy.model, "reasoning": {"effort": "medium"}}, lambda: SimpleNamespace(status_code=200))
        yield "http://127.0.0.1:1234"

    monkeypatch.setattr(coding, "provider_route", route)
    calls = []

    def execute(command, **kwargs):
        assert command[0] == str(tmp_path / "bcal.exe")
        assert "--include-evidence" in command
        assert kwargs["env"]["BCAL_REASONING_LOCAL_KEY"]
        private = tmp_path / "output" / selected.model
        (private / "exports").mkdir()
        if failure != "empty-export":
            (private / "exports" / "Probe.al").write_text("codeunit 50100 Probe {}")
        if failure == "auxiliary":
            (private / "auxiliary" / "invoked.json").write_text('{"providerAttempts":0}')
        transcript = {
            "schemaVersion": "1.0",
            "executionIdentity": {"sourceCommitSha": "wrong" if failure == "source" else "synthetic-source"},
            "runtimeIdentity": {"sdkPackageVersion": "1.0.29", "sdkRuntimeVersion": "1.0.107", "reasoningEffort": "medium"},
            "agentRuntimeEvidence": [{"compileCoversLatestChange": failure != "compile"}],
        }
        (private / "result.json").write_text(json.dumps(transcript))
        calls.append(command)
        if failure == "process":
            raise subprocess.CalledProcessError(1, ["private"])

    monkeypatch.setattr(agent, "_run_bcal_process", execute)
    verified = []

    def verify(*args, **kwargs):
        assert kwargs["config"].execution["auxiliary"]["completionReviewModel"] is None
        verified.append(True)

    monkeypatch.setattr(agent, "_require_completed", verify)
    args = Namespace(config=tmp_path / "config.json", scenario=tmp_path / "scenario.json", symbols=symbols, output=tmp_path / "output", package=tmp_path, archive=tmp_path / "archive", execute=True)
    if failure:
        with pytest.raises(subprocess.CalledProcessError if failure == "process" else coding.AdmissionError):
            coding.run_coding(args)
    else:
        coding.run_coding(args)
    receipt = json.loads((args.output / "receipt.json").read_bytes())
    assert len(calls) == 1
    assert len(verified) == (0 if failure in ("process", "auxiliary", "source") else 1)
    assert receipt["status"] == ("failed" if failure else "completed")
    assert receipt["arms"][0]["status"] == receipt["status"]
    assert receipt["arms"][0]["runtimeCleanupVerified"] is True
    assert receipt["arms"][0]["auxiliaryInvocations"] == (1 if failure == "auxiliary" else 0)
    assert receipt["accounting"]["attempts"] == 1
    assert "Implement synthetic" not in json.dumps(receipt)
    if failure:
        assert receipt["accounting"]["stopped"]
    else:
        assert receipt["arms"][0]["runtimeAppliedEffort"] == "medium"


def test_actual_package_offline_preparation_verifies_payload_and_cli_identity(tmp_path):
    root = os.environ.get("BCAL_OFFLINE_PACKAGE_ROOT")
    archive = os.environ.get("BCAL_OFFLINE_PACKAGE_ARCHIVE")
    if not root or not archive:
        pytest.skip("Set the exact existing package paths for offline packaged admission.")
    package = Path(root)
    assert coding.verify_package(package, Path(archive)) == 224
    result = subprocess.run([str(package / "bcal.exe"), "--version"], capture_output=True, text=True, timeout=30, check=True, env=coding.process_environment())
    assert result.stdout.strip() == "30.0.46.49019+" + coding.PACKAGE_SOURCE


@pytest.mark.parametrize("outcome", ["429", "missing-checklist", "success"])
def test_real_pinned_scorer_does_not_retry429_or_pad_missing_assertions(tmp_path, outcome):
    python = os.environ.get("BCAL_OFFLINE_JUDGE_PYTHON", sys.executable)
    probe = subprocess.run([python, "-c", "import autoevals,bc_eval,openai,httpx2,pydantic"], capture_output=True, check=False)
    if probe.returncode:
        pytest.skip("Set BCAL_OFFLINE_JUDGE_PYTHON to the existing pinned scorer environment.")
    launcher = """
import json, os, socket, sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import bcal_reasoning_coding as coding
import httpx2 as httpx
import openai
def forbidden(*args,**kwargs):
    raise AssertionError('Network forbidden')
socket.socket.connect=socket.socket.connect_ex=socket.getaddrinfo=forbidden
calls=[]
def respond(request):
    calls.append(True)
    assert len(calls)==1
    body=json.loads(request.content)
    assert body['model']=='gpt-56-ceres' and 'reasoning_effort' not in body
    if sys.argv[2]=='429':
        return httpx.Response(429,json={'error':{'message':'PRIVATE'}})
    content=json.dumps({'assertions':[] if sys.argv[2]=='missing-checklist' else [{'text':'PRIVATE','pass':True}]})
    return httpx.Response(200,json={'id':'offline','object':'chat.completion','created':0,'model':'gpt-56-ceres','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':content}}]})
events=[]
job={'input':'PRIVATE','output':'PRIVATE','expected':{'assertions':[{'text':'PRIVATE','level':'expected'}]}}
try:
    with openai.OpenAI(base_url='https://offline.invalid',api_key='local',max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
        result=coding.score_checklist(job,client,events.append)
    assert sys.argv[2]=='success' and result=={'quality':1.0,'testPassed':True}
except coding.JudgeRequestError:
    assert sys.argv[2]!='success'
finally:
    Path(sys.argv[3]).write_text(json.dumps({'calls':len(calls),'events':events}))
"""
    result = subprocess.run(
        [python, "-c", launcher, str(ROOT / "scripts"), outcome, str(tmp_path / "receipt.json")],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={**os.environ, "JUDGE_MODEL": "gpt-56-ceres"},
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "receipt.json").read_bytes())
    assert receipt["calls"] == 1
    assert "PRIVATE" not in json.dumps(receipt) + result.stdout + result.stderr
    if outcome == "429":
        assert receipt["events"][-1]["httpStatus"] == 429
