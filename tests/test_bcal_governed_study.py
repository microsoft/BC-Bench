import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("governed_study_test", ROOT / "scripts" / "bcal_governed_study.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)
transport_spec = importlib.util.spec_from_file_location("governed_transport_diagnostics_test", ROOT / "scripts" / "bcal_study_transport.py")
transport = importlib.util.module_from_spec(transport_spec)
transport_spec.loader.exec_module(transport)


@pytest.mark.parametrize("stage", ["request", "body", "non200", "success"])
def test_legacy_transport_distinguishes_headers_from_body_failure(stage):
    httpx = pytest.importorskip("httpx2")

    events = []
    private = "PRIVATE PROMPT RESPONSE SECRET"

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield private.encode()
            if stage == "body":
                raise httpx.ReadError(private)

    def respond(request):
        if stage == "request":
            raise httpx.ConnectTimeout(private, request=request)
        return httpx.Response(503 if stage == "non200" else 200, stream=Stream())

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        request = client.build_request("POST", "https://offline.invalid", content=private)

        def run():
            with transport.forward_response(client, request, RuntimeError, events.append) as response:
                assert response.status_code == (503 if stage == "non200" else 200)
                assert b"".join(response.iter_bytes()) == private.encode()

        if stage in {"request", "body"}:
            with pytest.raises(RuntimeError, match="Governed transport failed"):
                run()
            assert events[-1] == {"phase": stage, "outcome": "failed", "category": "timeout" if stage == "request" else "transport"}
        else:
            run()
            assert events[-1] == {"phase": "body", "outcome": "completed"}
        if stage != "request":
            assert events[0] == {"phase": "headers", "outcome": "received", "httpStatus": 503 if stage == "non200" else 200}
    assert private not in json.dumps(events)


@pytest.mark.parametrize("failure", ["non200", "transport", "json", "validation", "empty_choices", "missing_message", "success"])
def test_legacy_bridge_retains_failure_boundary_without_content_or_retries(tmp_path, monkeypatch, failure):
    import io
    import sys
    from types import SimpleNamespace

    httpx = pytest.importorskip("httpx2")
    openai = pytest.importorskip("openai")

    private = "PRIVATE PROMPT RESPONSE SECRET"
    calls = []
    real_openai = openai.OpenAI

    def respond(request):
        calls.append(request)
        if failure == "transport":
            raise httpx.ReadError(private, request=request)
        if failure == "non200":
            return httpx.Response(503, json={"error": {"message": private}})
        if failure == "json":
            return httpx.Response(200, content=b"{", headers={"content-type": "application/json"})
        body = {
            "id": "offline",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-56-reasoning-sol",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": private}}],
        }
        if failure == "validation":
            body["choices"] = private
        elif failure == "empty_choices":
            body["choices"] = []
        elif failure == "missing_message":
            body["choices"] = [{"index": 0, "finish_reason": "stop"}]
        return httpx.Response(200, json=body)

    def client(**kwargs):
        return real_openai(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond)), _strict_response_validation=failure == "validation")

    monkeypatch.setattr(openai, "OpenAI", client)
    monkeypatch.setenv("BCAL_STUDY_BRIDGE_DIAGNOSTICS", str(tmp_path))
    monkeypatch.setenv("BCAL_LLM_MODEL", "gpt-56-reasoning-sol")
    monkeypatch.setenv("BCAL_STUDY_REASONING_EFFORT", "none")
    monkeypatch.setenv("BCAL_STUDY_CHAT_URL", "https://offline.invalid")
    monkeypatch.setenv("BCAL_SDK_PROXY_KEY", private)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps({"model": "gpt-56-reasoning-sol", "messages": [{"role": "user", "content": private}]}).encode())))
    stdout = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=stdout))
    if failure in {"non200", "transport", "json", "validation"}:
        with pytest.raises((openai.OpenAIError, json.JSONDecodeError)):
            transport.bridge()
        assert stdout.getvalue() == b""
    else:
        transport.bridge()
        assert isinstance(json.loads(stdout.getvalue()), dict)
    assert len(calls) == 1
    assert json.loads(calls[0].content)["reasoning_effort"] == "none"
    receipts = list(tmp_path.glob("bridge-*.json"))
    assert len(receipts) == 1
    safe = study.legacy_diagnostic_receipt(receipts[0])
    assert safe["valid"] is True
    assert private not in json.dumps(safe)
    events = safe["events"]
    if failure in {"non200", "transport", "json", "validation"}:
        diagnostic = next(event for event in events if event["phase"] == "client" and event["outcome"] == "failed")
        assert diagnostic["category"] == {"non200": "http_status", "transport": "transport", "json": "json_decode", "validation": "response_validation"}[failure]
        if failure == "non200":
            assert diagnostic["httpStatus"] == 503
    else:
        assert (
            next(event for event in events if event["phase"] == "response")["outcome"]
            == {"empty_choices": "empty_choices", "missing_message": "missing_message", "success": "message_present"}[failure]
        )
        assert events[-1]["outcome"] == "emitted"


@pytest.mark.parametrize("encoding", ["ascii", "cp1252"])
@pytest.mark.parametrize("call_site", ["delivery", "completion_assessment"])
def test_legacy_bridge_subprocess_emits_exact_utf8_independent_of_child_encoding(tmp_path, encoding, call_site):
    import os
    import subprocess
    import sys

    pytest.importorskip("httpx2")
    pytest.importorskip("openai")
    from openai.types.chat import ChatCompletion

    private = "PRIVATE \u6f22\u5b57 \U0001f600"
    message = {"role": "assistant", "content": private}
    request = {"model": "gpt-56-reasoning-sol", "messages": [{"role": "user", "content": private}]}
    if call_site == "delivery":
        request["tools"] = [{"type": "function", "function": {"name": "offline", "parameters": {"type": "object"}}}]
        message["tool_calls"] = [{"id": "offline", "type": "function", "function": {"name": "offline", "arguments": json.dumps({"text": private}, ensure_ascii=False)}}]
    response = {"id": "offline", "object": "chat.completion", "created": 0, "model": request["model"], "choices": [{"index": 0, "finish_reason": "stop", "message": message}]}
    launcher = """
import json, os, runpy, socket, sys
import httpx2 as httpx
import openai
assert sys.stdout.encoding == os.environ["TEST_STDOUT_ENCODING"]
def forbidden(*args, **kwargs):
    raise AssertionError("Network forbidden")
socket.socket.connect = socket.socket.connect_ex = socket.getaddrinfo = forbidden
calls = []
def respond(request):
    calls.append(request)
    assert len(calls) == 1
    body = json.loads(request.content)
    assert body["reasoning_effort"] == "none"
    assert body["max_completion_tokens"] == 16384
    assert body["messages"][0]["content"] == "PRIVATE \\u6f22\\u5b57 \\U0001f600"
    assert ("tools" in body) == (os.environ["TEST_CALL_SITE"] == "delivery")
    return httpx.Response(200, json=json.loads(os.environ["TEST_RESPONSE"]))
real_client = openai.OpenAI
openai.OpenAI = lambda **kwargs: real_client(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond)))
sys.argv = [sys.argv[1], "bridge"]
runpy.run_path(sys.argv[0], run_name="__main__")
assert len(calls) == 1
"""
    env = {
        **os.environ,
        "PYTHONUTF8": "0",
        "PYTHONIOENCODING": encoding,
        "TEST_STDOUT_ENCODING": encoding,
        "TEST_CALL_SITE": call_site,
        "TEST_RESPONSE": json.dumps(response),
        "BCAL_LLM_MODEL": request["model"],
        "BCAL_STUDY_REASONING_EFFORT": "none",
        "BCAL_STUDY_CHAT_URL": "https://offline.invalid",
        "BCAL_SDK_PROXY_KEY": "PRIVATE TEST KEY",
        "BCAL_STUDY_BRIDGE_DIAGNOSTICS": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "-c", launcher, str(ROOT / "scripts" / "bcal_study_transport.py")],
        input=json.dumps(request, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=env,
        timeout=30,
        check=True,
    )
    assert result.stderr == ""
    assert result.stdout == ChatCompletion.model_validate(response).model_dump_json(exclude_none=True)
    assert json.loads(result.stdout)["choices"][0]["message"] == message
    receipts = list(tmp_path.glob("bridge-*.json"))
    assert len(receipts) == 1
    safe = study.legacy_diagnostic_receipt(receipts[0])
    assert safe["valid"] is True
    assert [(event["phase"], event["outcome"]) for event in safe["events"]] == [
        ("command", "started"),
        ("client", "started"),
        ("response", "message_present"),
        ("command", "emitted"),
    ]
    assert "PRIVATE" not in json.dumps(safe)


@pytest.mark.parametrize("failure", ["encoding", "write", "flush"])
def test_legacy_bridge_output_failures_preserve_stage_original_error_and_no_content(tmp_path, monkeypatch, failure):
    import io
    import sys
    from contextlib import nullcontext
    from types import SimpleNamespace

    openai = pytest.importorskip("openai")
    private = "PRIVATE PROMPT RESPONSE SECRET"
    content = private + ("\ud800" if failure == "encoding" else "")
    response = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}, ensure_ascii=False)
    error = OSError(private)

    class Output(io.BytesIO):
        def write(self, data):
            if failure == "write":
                raise error
            return super().write(data)

        def flush(self):
            if failure == "flush":
                raise error
            super().flush()

    monkeypatch.setattr(
        openai, "OpenAI", lambda **_: nullcontext(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: SimpleNamespace(model_dump_json=lambda **_: response)))))
    )
    monkeypatch.setenv("BCAL_STUDY_BRIDGE_DIAGNOSTICS", str(tmp_path))
    monkeypatch.setenv("BCAL_LLM_MODEL", "gpt-56-reasoning-sol")
    monkeypatch.setenv("BCAL_STUDY_REASONING_EFFORT", "none")
    monkeypatch.setenv("BCAL_STUDY_CHAT_URL", "https://offline.invalid")
    monkeypatch.setenv("BCAL_SDK_PROXY_KEY", private)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps({"model": "gpt-56-reasoning-sol", "messages": []}).encode())))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=Output()))
    with pytest.raises(UnicodeEncodeError if failure == "encoding" else OSError) as caught:
        transport.bridge()
    if failure != "encoding":
        assert caught.value is error
    safe = study.legacy_diagnostic_receipt(next(tmp_path.glob("bridge-*.json")))
    assert safe["valid"] is True
    assert {key: safe["events"][-2][key] for key in ("phase", "outcome", "category")} == {
        "phase": "output",
        "outcome": "failed",
        "category": "unicode_encode" if failure == "encoding" else "command_io",
    }
    assert safe["events"][-1]["outcome"] == "failed"
    assert safe["events"][-1]["category"] == ("unicode_encode" if failure == "encoding" else "unknown")
    assert not any(event["outcome"] == "emitted" for event in safe["events"])
    assert private not in json.dumps(safe)


def test_legacy_bridge_input_decoding_is_not_reclassified_as_output_encoding(tmp_path, monkeypatch):
    import io
    import sys
    from types import SimpleNamespace

    pytest.importorskip("openai")
    monkeypatch.setenv("BCAL_STUDY_BRIDGE_DIAGNOSTICS", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"PRIVATE\xff")))
    with pytest.raises(UnicodeDecodeError):
        transport.bridge()
    safe = study.legacy_diagnostic_receipt(next(tmp_path.glob("bridge-*.json")))
    assert [(event["phase"], event.get("category")) for event in safe["events"]] == [("command", None), ("input", "body_decode"), ("command", "body_decode")]
    assert "PRIVATE" not in json.dumps(safe)


def test_legacy_diagnostic_receipt_redacts_unknowns_and_does_not_fabricate_missing_evidence(tmp_path):
    path = tmp_path / "safe.json"
    assert study.legacy_diagnostic_receipt(path) == {"available": False, "events": None}
    path.write_text("{")
    assert study.legacy_diagnostic_receipt(path)["valid"] is False
    study.write_json(
        path,
        {
            "schemaVersion": 1,
            "events": [{"phase": "PRIVATE", "outcome": "PRIVATE", "category": "PRIVATE", "httpStatus": True, "requestsObserved": 3, "message": "PRIVATE", "Authorization": "PRIVATE"}],
        },
    )
    safe = study.legacy_diagnostic_receipt(path)
    assert safe["events"] == [{"phase": None, "outcome": None, "category": None, "httpStatus": None, "requestsObserved": 3}]
    assert "PRIVATE" not in json.dumps(safe)


def test_interruption_projection_retains_only_known_enums_and_hashes():
    trace = {
        "truncated": False,
        "omittedEventCount": 0,
        "events": [
            {"type": "model_interrupted", "operation": "delivery", "status": "interrupted", "interruptionReason": "failed", "message": "PRIVATE", "callId": "PRIVATE"},
            {"type": "turn_interrupted", "operation": "turn", "status": "canceled", "interruptionReason": "canceled"},
            {"type": "model_interrupted", "operation": "PRIVATE", "status": "PRIVATE", "interruptionReason": "PRIVATE"},
        ],
    }
    safe = study.trace_projection({"evidence": {"trace": trace}})
    assert safe["complete"] is True
    assert safe["events"][0]["type"] == "model_interrupted"
    assert {key: safe["events"][0][key] for key in ("operation", "status", "interruptionReason")} == {"operation": "delivery", "status": "interrupted", "interruptionReason": "failed"}
    assert safe["events"][1]["status"] == "canceled"
    assert safe["events"][2]["interruptionReason"] is None
    assert "PRIVATE" not in json.dumps(safe)


def test_actual_producer_fixture_preserves_failure_and_correlation_without_content():
    event = json.loads((ROOT / "tests" / "fixtures" / "bcal_legacy_model_interrupted.json").read_bytes())
    event["message"] = "PRIVATE"
    event["modelFailure"].update(stack="PRIVATE", command="PRIVATE", exceptionType="PRIVATE")
    safe = study.trace_projection({"evidence": {"trace": {"truncated": False, "omittedEventCount": 0, "events": [event]}}})
    failure = safe["events"][0]
    assert failure["modelFailure"] == {"stage": "response_choices", "exceptionCategory": "argument", "exitCode": 0}
    assert (failure["turn"], failure["iteration"], failure["promptUseSequence"]) == (3, 4, 1)
    assert failure["callIdSha256"] == hashlib.sha256(event["callId"].encode()).hexdigest()
    assert failure["scenarioStepIdSha256"] == hashlib.sha256(event["scenarioStepId"].encode()).hexdigest()
    assert failure["compositionIdSha256"] == hashlib.sha256(event["compositionId"].encode()).hexdigest()
    assert "PRIVATE" not in json.dumps(safe)


@pytest.mark.parametrize("failure", [None, {"stage": "ResponseChoices", "exceptionCategory": "PRIVATE", "exitCode": True}, {"stage": "unknown", "exceptionCategory": "unknown", "exitCode": 2**31}])
def test_product_failure_projection_preserves_unknowns_without_casing_or_exit_coercion(failure):
    event = {"type": "model_interrupted", "modelFailure": failure}
    safe = study.trace_projection({"evidence": {"trace": {"events": [event]}}})["events"][0]["modelFailure"]
    if failure is None:
        assert safe is None
    else:
        assert safe["exitCode"] is None
        assert safe["stage"] == ("unknown" if failure["stage"] == "unknown" else None)
        assert "PRIVATE" not in json.dumps(safe)


def test_legacy_body_client_disconnect_is_not_reported_as_completed():
    httpx = pytest.importorskip("httpx2")
    events = []
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"private"))) as client:
        request = client.build_request("POST", "https://offline.invalid")
        with pytest.raises(BrokenPipeError), transport.forward_response(client, request, RuntimeError, events.append):
            raise BrokenPipeError("PRIVATE")
    assert events[-1] == {"phase": "body", "outcome": "failed", "category": "client_disconnect"}
    assert not any(event["outcome"] == "completed" for event in events)
    assert "PRIVATE" not in json.dumps(events)


def test_attempt_finally_preserves_legacy_diagnostics_without_runtime_success(tmp_path, monkeypatch):
    work = tmp_path / "attempt"
    public = tmp_path / "public.json"
    monkeypatch.setenv("BCAL_STUDY_WORK", str(tmp_path))

    def fail(_):
        study.write_json(
            work / "HostAgent-chat-completions.audit.diagnostics.json", {"schemaVersion": 1, "events": [{"phase": "headers", "outcome": "received", "httpStatus": 503, "message": "PRIVATE"}]}
        )
        (work / "bridge-diagnostics").mkdir()
        study.write_json(work / "bridge-diagnostics" / "bridge-test.json", {"schemaVersion": 1, "events": [{"phase": "command", "outcome": "started"}]})
        raise ValueError("PRIVATE")

    monkeypatch.setattr(study, "verify_package", fail)
    with pytest.raises(ValueError, match="PRIVATE"):
        study.run_attempt(study.pairs()[0], "legacy", work, {}, public)
    value = json.loads(public.read_bytes())
    assert value["status"] == "evidence-or-infrastructure-error"
    assert value["quality"] is None
    assert value["legacyDiagnostics"]["transport"]["events"] == [{"phase": "headers", "outcome": "received", "httpStatus": 503}]
    assert value["legacyDiagnostics"]["bridgeInvocations"][0]["events"] == [{"phase": "command", "outcome": "started"}]
    assert "runtimeClientException" not in value["legacyDiagnostics"]
    assert value["legacyDiagnostics"]["invocationOrder"] == "not-established"
    assert "PRIVATE" not in json.dumps(value)


def test_fixed_cohort_is_repeat_aware_and_counterbalanced():
    pairs = study.pairs()
    assert len({(pair["tier"], pair["instanceId"]) for pair in pairs}) == 8
    assert len({(pair["instanceId"], pair["repeat"], runtime) for pair in pairs for runtime in pair["order"]}) == 16
    for first, second in zip(pairs[::2], pairs[1::2], strict=True):
        assert first["order"] == second["order"][::-1]
    assert {pair["repeat"] for pair in pairs} == {1}
    assert sum(pair["lane"] == "authority" for pair in pairs) == 4
    assert {pair["instanceId"] for pair in pairs if pair["lane"] == "ordinary-quality"} == {
        "nl2al__move-name-customer-card-2",
        "nl2al__add-industry-field-customer-card-2",
        "nl2al__event-subscriber-onafterpostsalesdoc-2",
        "nl2al__customer-internal-notes-blob-2",
    }


def test_full_gold_selects_every_case_once_per_runtime(monkeypatch):
    monkeypatch.setattr(study, "INPUTS", ROOT / "experiments" / "bcal-full-gold")
    pairs = study.pairs()
    gold = [json.loads(line) for line in (ROOT / "dataset" / "nl2al.jsonl").read_text().splitlines() if line]
    assert len(pairs) == 110
    assert {pair["instanceId"] for pair in pairs} == {row["instance_id"] for row in gold}
    assert len({(pair["instanceId"], runtime) for pair in pairs for runtime in pair["order"]}) == 220
    assert all(pair["tier"] == "gold" and pair["lane"] == "ordinary-quality" and pair["category"] == "nl2al" for pair in pairs)
    assert study.study()["inference"]["model"] == "gpt-56-reasoning-sol"
    assert study.study()["inference"]["reasoning"] == "none"


def test_full_gold_rejects_hidden_exclusions(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "INPUTS", ROOT / "experiments" / "bcal-full-gold")
    config = study.study()
    config["datasets"][0]["selectedEntries"].pop()
    study.write_json(tmp_path / "study.json", config)
    monkeypatch.setattr(study, "INPUTS", tmp_path)
    with pytest.raises(ValueError, match="without exclusions"):
        study.pairs()


@pytest.mark.parametrize("line_ending", [b"\n", b"\r\n"])
def test_repeat_preserves_git_baseline_across_checkout_line_endings(tmp_path, monkeypatch, line_ending):
    config = json.loads((ROOT / "experiments" / "bcal-full-gold-repeat" / "study.json").read_bytes())
    baseline_bytes = (ROOT / config["baselineStudy"]["file"]).read_bytes().replace(b"\r\n", b"\n")
    baseline = json.loads(baseline_bytes)
    baseline_path = tmp_path / config["baselineStudy"]["file"]
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_bytes(baseline_bytes.replace(b"\n", line_ending))
    inputs = tmp_path / "repeat"
    study.write_json(inputs / "study.json", config)
    monkeypatch.setattr(study, "ROOT", tmp_path)
    monkeypatch.setattr(study, "INPUTS", inputs)

    assert study.study_manifest()["datasets"] == baseline["datasets"]
    assert study.study_manifest()["inference"] == baseline["inference"]
    assert study.study_manifest()["judge"] == baseline["judge"]

    baseline["datasets"][0]["selectedEntries"].pop()
    study.write_json(baseline_path, baseline)
    with pytest.raises(ValueError, match="Original full-gold manifest changed"):
        study.study_manifest()


def test_repeat_rejects_unadmitted_or_historical_package_and_selection_overrides(tmp_path, monkeypatch):
    config = json.loads((ROOT / "experiments" / "bcal-full-gold-repeat" / "study.json").read_bytes())
    config.update(package=None, runtimeDiagnosticsProof=None)
    monkeypatch.setattr(study, "INPUTS", tmp_path)
    study.write_json(tmp_path / "study.json", config)
    with pytest.raises(ValueError, match="diagnostic runtime package"):
        study.study()
    baseline = json.loads((ROOT / config["baselineStudy"]["file"]).read_bytes())
    config["package"] = baseline["package"]
    study.write_json(tmp_path / "study.json", config)
    with pytest.raises(ValueError, match="diagnostic runtime package"):
        study.study()
    config["package"] = {**baseline["package"], "sha256": "0" * 64, "sourceCommitSha": "0" * 40}
    for key in ("sha256", "sourceCommitSha"):
        valid = config["package"][key]
        config["package"][key] = None
        study.write_json(tmp_path / "study.json", config)
        with pytest.raises(ValueError, match="diagnostic runtime package"):
            study.study()
        config["package"][key] = valid
    study.write_json(tmp_path / "study.json", config)
    with pytest.raises(ValueError, match="producer proof"):
        study.study()
    config["runtimeDiagnosticsProof"] = {"file": "test-only.json", "sha256": "0" * 64}
    study.write_json(tmp_path / "study.json", config)
    pairs = study.pairs()
    assert len(pairs) == 110
    assert len({(pair["instanceId"], runtime) for pair in pairs for runtime in pair["order"]}) == 220
    assert study.study()["datasets"] == baseline["datasets"]
    assert study.study()["inference"] == baseline["inference"]
    assert study.study()["judge"] == baseline["judge"]
    config["datasets"] = []
    study.write_json(tmp_path / "study.json", config)
    with pytest.raises(ValueError, match="cannot be overridden"):
        study.study()


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "packageSha256",
        "commandClientInvoked",
        "invocationCollectorInvoked",
        "consumerProjectionVerified",
        "providerRequests",
        "observedModelInterruptions",
        "missingModelFailure",
        "rawException",
        "booleanExit",
        "overflowExit",
    ],
)
def test_repeat_requires_actual_packaged_diagnostics_and_consumer_proof(tmp_path, monkeypatch, invalid):
    from argparse import Namespace

    config = json.loads((ROOT / "experiments" / "bcal-full-gold" / "study.json").read_bytes())
    config["repeatOf"] = {"runId": 43422730966}
    proof = {
        "status": "passed",
        "packageSha256": config["package"]["sha256"],
        "packageSourceCommitSha": config["package"]["sourceCommitSha"],
        "commandClientInvoked": True,
        "invocationCollectorInvoked": True,
        "consumerProjectionVerified": True,
        "providerRequests": 0,
        "observedModelInterruptions": [
            {"type": "model_interrupted", "modelFailure": {"stage": stage, "exceptionCategory": "unknown"}}
            for stage in ("command_start", "command_io", "command_exit", "response_json", "response_choices", "response_message")
        ],
    }
    if invalid == "missingModelFailure":
        del proof["observedModelInterruptions"][0]["modelFailure"]
    elif invalid == "rawException":
        proof["observedModelInterruptions"][0]["modelFailure"]["exceptionMessage"] = "PRIVATE"
    elif invalid == "booleanExit":
        proof["observedModelInterruptions"][0]["modelFailure"]["exitCode"] = False
    elif invalid == "overflowExit":
        proof["observedModelInterruptions"][0]["modelFailure"]["exitCode"] = 2**31
    elif invalid is not None:
        proof[invalid] = False
    path = tmp_path / "proof.json"
    study.write_json(path, proof)
    config["runtimeDiagnosticsProof"] = {"file": path.name, "sha256": study.digest(path)}
    monkeypatch.setattr(study, "ROOT", tmp_path)
    monkeypatch.setattr(study, "study", lambda: config)
    if invalid:
        with pytest.raises(ValueError, match=r"verified|boundaries"):
            study.preflight(Namespace(work=tmp_path, output=tmp_path))
        assert not (tmp_path / "package").exists()
    else:
        assert study.verify_runtime_diagnostics_proof() == config["runtimeDiagnosticsProof"]
        path.write_text("{}")
        with pytest.raises(ValueError, match="binding differs"):
            study.verify_runtime_diagnostics_proof()


def test_full_gold_summary_keeps_all_unattempted_cells(tmp_path, monkeypatch):
    from argparse import Namespace

    monkeypatch.setattr(study, "INPUTS", ROOT / "experiments" / "bcal-full-gold")
    with pytest.raises(ValueError, match="incomplete"):
        study.summary(Namespace(work=tmp_path, output=tmp_path / "summary"))
    result = json.loads((tmp_path / "summary" / "comparison.json").read_bytes())
    assert result["expected"] == 220
    assert len(result["missing"]) == 220
    assert set(result["lanes"]) == {"ordinary-quality"}
    assert result["lanes"]["ordinary-quality"]["legacy"]["expected"] == 110


def test_legacy_only_gold_selects_exact_original_cases_without_sdk_slots(monkeypatch, tmp_path):
    from argparse import Namespace

    monkeypatch.setattr(study, "INPUTS", ROOT / "experiments" / "bcal-full-gold-legacy-utf8")
    config = study.study()
    selected = study.pairs()
    assert config["variants"] == ["legacy"]
    assert len(selected) == 110
    assert all(row["order"] == ["legacy"] for row in selected)
    assert {row["instanceId"] for row in selected} == {row["instanceId"] for row in config["datasets"][0]["selectedEntries"]}
    with pytest.raises(ValueError, match="incomplete"):
        study.summary(Namespace(work=tmp_path, output=tmp_path / "summary"))
    result = json.loads((tmp_path / "summary" / "comparison.json").read_bytes())
    assert result["expected"] == len(result["missing"]) == 110
    assert set(result["lanes"]["ordinary-quality"]) == {"legacy"}
    with pytest.raises(ValueError, match="outside"):
        study.run_attempt(selected[0], "copilot-sdk", tmp_path / "invalid", {}, tmp_path / "invalid.json")
    assert not (tmp_path / "invalid").exists()


@pytest.mark.parametrize("mutation", ["variants", "datasets", "judge", "legacyValidationOf"])
def test_legacy_only_gold_rejects_workload_expansion(tmp_path, monkeypatch, mutation):
    directory = tmp_path / "profile"
    directory.mkdir()
    value = json.loads((ROOT / "experiments" / "bcal-full-gold-legacy-utf8" / "study.json").read_bytes())
    value[mutation] = {}
    study.write_json(directory / "study.json", value)
    monkeypatch.setattr(study, "INPUTS", directory)
    with pytest.raises(ValueError, match="separately approved"):
        study.study()


@pytest.mark.parametrize("mutation", ["inventory", "hash", "content"])
def test_legacy_proof_requires_exact_git_canonical_sources(tmp_path, monkeypatch, mutation):
    sources = {"scripts\\bcal_governed_study.py": b"one\n", "scripts\\bcal_study_transport.py": b"two\n", "src\\bcbench\\agent\\bcal\\bc_eval_sdk_proxy.py": b"three\n"}
    for filename, content in sources.items():
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.replace(b"\n", b"\r\n"))
    proof = {"sourceHashes": {filename: hashlib.sha256(content).hexdigest() for filename, content in sources.items()}}
    monkeypatch.setattr(study, "ROOT", tmp_path)
    monkeypatch.setattr(study.subprocess, "check_output", lambda args, **_: sources[args[-1][5:].replace("/", "\\")])
    study.verify_proof_sources(proof)
    if mutation == "inventory":
        proof["sourceHashes"].pop("scripts\\bcal_study_transport.py")
    elif mutation == "hash":
        proof["sourceHashes"]["scripts\\bcal_study_transport.py"] = "0" * 64
    else:
        (tmp_path / "scripts\\bcal_study_transport.py").write_bytes(b"two \n")
    with pytest.raises(ValueError, match=r"source|content"):
        study.verify_proof_sources(proof)


@pytest.mark.parametrize("fail_at", [None, 2])
def test_legacy_only_admission_uses_two_real_command_slots_and_one_judge_without_responses(tmp_path, monkeypatch, fail_at):
    import io
    from argparse import Namespace
    from contextlib import contextmanager
    from types import SimpleNamespace

    monkeypatch.setattr(study, "INPUTS", ROOT / "experiments" / "bcal-full-gold-legacy-utf8")
    monkeypatch.setattr(study, "verify_runtime_diagnostics_proof", dict)
    monkeypatch.setattr(study, "verify_runtime_effort_proof", dict)
    monkeypatch.setenv("BCAL_STUDY_INFERENCE_PYTHON", "offline")
    current, requests = {}, []

    @contextmanager
    def proxy(_work, env, model, wire, role):
        assert wire == "chat-completions"
        assert env["BCAL_AGENT_RUNTIME"] == "legacy"
        current.update(model=model, role=role, count=0, audit=tmp_path / f"{role}.json")
        study.write_json(current["audit"], {"requests": 0, "http200": 0, "ticketsReturned": 0, "ticketsReplayed": 0, "sessionStable": True, "modelStable": True})
        yield "https://offline.invalid", current["audit"]

    def respond(body):
        requests.append((current["role"], body))
        current["count"] += 1
        count = current["count"]
        failed = len(requests) == fail_at
        values = {"requests": count, "http200": count - failed, "ticketsReturned": count - failed, "ticketsReplayed": count - 1, "sessionStable": True, "modelStable": True}
        if current["role"] == "HostAgent":
            values.update(reasoningEffort="none", effortVerifiedRequests=count, effortRejectedRequests=0)
            assert body["reasoning_effort"] == "none"
        study.write_json(current["audit"], values)
        if failed:
            raise TimeoutError("offline")
        return {"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]}

    def command(args, *, input, env, **kwargs):
        assert args[-1] == "bridge"
        assert env["BCAL_STUDY_REASONING_EFFORT"] == "none"
        body = json.loads(input)
        result = respond(body)
        study.write_json(Path(env["BCAL_STUDY_BRIDGE_DIAGNOSTICS"]) / f"bridge-{len(requests)}.json", {"schemaVersion": 1, "events": [{"phase": "command", "outcome": "emitted"}]})
        return SimpleNamespace(stdout=json.dumps(result).encode())

    monkeypatch.setattr(study, "proxy", proxy)
    monkeypatch.setattr(study.subprocess, "run", command)
    monkeypatch.setattr(study.urllib.request, "urlopen", lambda request, **_: io.StringIO(json.dumps(respond(json.loads(request.data)))))
    if fail_at:
        with pytest.raises(TimeoutError):
            study.routing_preflight(Namespace(work=tmp_path, output=tmp_path))
    else:
        study.routing_preflight(Namespace(work=tmp_path, output=tmp_path))
    receipt = json.loads((tmp_path / "routing-preflight.json").read_bytes())
    assert receipt["requests"] == len(requests) == (fail_at or 3)
    assert receipt["requestLimit"] == 3
    assert [role for role, _ in requests] == ["HostAgent", "HostAgent"] + ([] if fail_at else ["Judge"])
    assert receipt["status"] == ("failed" if fail_at else "passed")
    if not fail_at:
        assert len(receipt["routes"][0]["bridgeInvocations"]) == 2


@pytest.mark.parametrize("fail_at", [None, 2])
def test_full_gold_routing_admission_is_bounded_and_preserves_partial_charges(tmp_path, monkeypatch, fail_at):
    import io
    from argparse import Namespace
    from contextlib import contextmanager

    monkeypatch.setattr(study, "INPUTS", ROOT / "experiments" / "bcal-full-gold")
    requests = []
    current = {}

    @contextmanager
    def fake_proxy(_work, _env, model, wire, role):
        current.update(model=model, wire=wire, audit=tmp_path / f"{role}-{wire}.json", count=0)
        study.write_json(current["audit"], {"requests": 0, "http200": 0, "ticketsReturned": 0, "ticketsReplayed": 0, "sessionStable": True, "modelStable": True})
        yield "http://unused.invalid", current["audit"]

    def respond(request, timeout):
        body = json.loads(request.data)
        assert body["model"] == current["model"]
        assert body["tools"]
        if current["wire"] == "responses":
            assert body["reasoning"] == {"effort": "none"}
            assert "tool_choice" not in body
            assert body["max_output_tokens"] == 1024
        elif current["model"] == "gpt-56-reasoning-sol":
            assert body["reasoning_effort"] == "none"
            assert body["max_completion_tokens"] == 16384
        else:
            assert set(body) == {"model", "messages", "tools", "max_completion_tokens"}
            assert body["max_completion_tokens"] == 16384
        requests.append(body)
        current["count"] += 1
        failed = len(requests) == fail_at
        count = current["count"]
        counters = {"requests": count, "http200": count - failed, "ticketsReturned": count - failed, "ticketsReplayed": count - 1, "sessionStable": True, "modelStable": True}
        if current["model"] == "gpt-56-reasoning-sol":
            counters.update(reasoningEffort="none", effortVerifiedRequests=count, effortRejectedRequests=0)
        study.write_json(current["audit"], counters)
        if failed:
            raise TimeoutError("simulated upstream failure")
        return io.StringIO(
            json.dumps({"status": "completed", "output": [{"type": "message"}]} if current["wire"] == "responses" else {"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]})
        )

    monkeypatch.setattr(study, "proxy", fake_proxy)
    monkeypatch.setattr(study.urllib.request, "urlopen", respond)
    args = Namespace(work=tmp_path, output=tmp_path)
    if fail_at:
        with pytest.raises(TimeoutError):
            study.routing_preflight(args)
    else:
        study.routing_preflight(args)
    receipt = json.loads((tmp_path / "routing-preflight.json").read_bytes())
    assert receipt["requests"] == len(requests) == (fail_at or 5)
    assert receipt["status"] == ("failed" if fail_at else "passed")
    if not fail_at:
        assert all(route["responseProtocolValid"] is True for route in receipt["routes"])
    assert all(body["model"] == "gpt-56-reasoning-sol" for body in requests[:4])


@pytest.mark.parametrize("effort", [None, "high"])
def test_sol_bridge_omits_default_effort_and_rejects_unspecified_effort_override(monkeypatch, effort):
    import io
    import sys
    from contextlib import nullcontext
    from types import ModuleType, SimpleNamespace

    transport_spec = importlib.util.spec_from_file_location("gold_transport_test", ROOT / "scripts" / "bcal_study_transport.py")
    transport = importlib.util.module_from_spec(transport_spec)
    transport_spec.loader.exec_module(transport)
    observed = []
    api = ModuleType("openai")

    def create(**kwargs):
        observed.append(kwargs)
        return SimpleNamespace(model_dump_json=lambda **_: "{}")

    api.OpenAI = lambda **_: nullcontext(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setitem(sys.modules, "openai", api)
    monkeypatch.setenv("BCAL_LLM_MODEL", "gpt-56-reasoning-sol")
    monkeypatch.setenv("BCAL_STUDY_CHAT_URL", "http://unused.invalid")
    monkeypatch.setenv("BCAL_SDK_PROXY_KEY", "test-only")
    body = {
        "model": "gpt-56-reasoning-sol",
        "messages": [{"role": "user", "content": "Return only OK."}],
        "reasoning_effort": effort,
        "tools": [{"type": "function", "function": {"name": "admission_probe", "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}}],
    }
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(body).encode())))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=io.BytesIO()))
    if effort:
        with pytest.raises(ValueError, match="governed policy"):
            transport.bridge()
        assert not observed
    else:
        transport.bridge()
        assert observed == [{"model": body["model"], "messages": body["messages"], "tools": body["tools"], "max_completion_tokens": 16384}]


@pytest.mark.parametrize("incoming", [None, "none", "high"])
def test_approved_bridge_applies_none_to_command_client_shape_and_rejects_conflict(monkeypatch, incoming):
    import io
    import sys
    from contextlib import nullcontext
    from types import ModuleType, SimpleNamespace

    spec = importlib.util.spec_from_file_location("explicit_effort_transport", ROOT / "scripts" / "bcal_study_transport.py")
    transport = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transport)
    observed = []
    api = ModuleType("openai")

    def create(**kwargs):
        observed.append(kwargs)
        return SimpleNamespace(model_dump_json=lambda **_: "{}")

    api.OpenAI = lambda **_: nullcontext(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setitem(sys.modules, "openai", api)
    monkeypatch.setenv("BCAL_LLM_MODEL", "gpt-56-reasoning-sol")
    monkeypatch.setenv("BCAL_STUDY_REASONING_EFFORT", "none")
    monkeypatch.setenv("BCAL_STUDY_CHAT_URL", "http://unused.invalid")
    monkeypatch.setenv("BCAL_SDK_PROXY_KEY", "offline-only")
    body = {"model": "gpt-56-reasoning-sol", "messages": [{"role": "user", "content": "synthetic"}], "max_completion_tokens": 16384, "tools": [{"type": "function", "function": {"name": "probe"}}]}
    if incoming is not None:
        body["reasoning_effort"] = incoming
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(body).encode())))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=io.BytesIO()))
    if incoming == "high":
        with pytest.raises(ValueError, match="governed policy"):
            transport.bridge()
        assert not observed
    else:
        transport.bridge()
        assert observed == [{**body, "reasoning_effort": "none"}]


def test_gold_preflight_stops_before_package_or_auth_without_actual_sdk_proof(tmp_path, monkeypatch):
    from argparse import Namespace

    monkeypatch.setattr(study, "INPUTS", ROOT / "experiments" / "bcal-full-gold")
    config = study.study()
    config["runtimeEffortProof"] = None
    monkeypatch.setattr(study, "study", lambda: config)
    with pytest.raises(ValueError, match="SDK effort proof"):
        study.preflight(Namespace(work=tmp_path, output=tmp_path))
    assert json.loads((tmp_path / "preflight.json").read_bytes())["status"] == "failed"
    assert not (tmp_path / "package").exists()


@pytest.mark.parametrize("invalid", [None, "packageSha256", "observedSdkWireEffort", "nativeSdkInvoked", "legacyBridgeVerified", "mismatchRejectedBeforeProvider"])
def test_runtime_effort_proof_requires_package_bound_actual_sdk_and_bridge_evidence(tmp_path, monkeypatch, invalid):
    monkeypatch.setattr(study, "INPUTS", ROOT / "experiments" / "bcal-full-gold")
    config = study.study()
    proof = {
        "status": "passed",
        "packageSha256": config["package"]["sha256"],
        "packageSourceCommitSha": config["package"]["sourceCommitSha"],
        "requestedSdkEffort": "none",
        "observedSdkWireEffort": "none",
        "nativeSdkInvoked": True,
        "mismatchRejectedBeforeProvider": True,
        "legacyBridgeVerified": True,
    }
    if invalid is not None:
        proof[invalid] = False
    path = tmp_path / "proof.json"
    study.write_json(path, proof)
    config["runtimeEffortProof"] = {"file": path.name, "sha256": study.digest(path)}
    monkeypatch.setattr(study, "ROOT", tmp_path)
    monkeypatch.setattr(study, "study", lambda: config)
    if invalid:
        with pytest.raises(ValueError, match="fidelity"):
            study.verify_runtime_effort_proof()
    else:
        assert study.verify_runtime_effort_proof() == config["runtimeEffortProof"]
        path.write_text("{}")
        with pytest.raises(ValueError, match="binding differs"):
            study.verify_runtime_effort_proof()


@pytest.mark.parametrize("runtime", ["legacy", "copilot-sdk"])
def test_effort_guard_failure_preserves_prior_call_accounting_without_compliance(tmp_path, monkeypatch, runtime):
    import sys
    from contextlib import contextmanager

    from bcbench.agent.bcal import agent

    monkeypatch.setattr(study, "INPUTS", ROOT / "experiments" / "bcal-full-gold")
    monkeypatch.setenv("BCAL_STUDY_WORK", str(tmp_path))
    monkeypatch.setenv("BCAL_STUDY_INFERENCE_PYTHON", sys.executable)
    monkeypatch.setattr(study, "verify_package", lambda _: tmp_path / "bcal.exe")
    monkeypatch.setattr(agent, "_run_bcal_process", lambda *_args, **_kwargs: None)

    @contextmanager
    def fake_proxy(work, env, model, wire, role):
        assert env["BCAL_STUDY_REASONING_EFFORT"] == "none"
        path = work / f"{role}-{wire}.audit.json"
        failing = wire == ("responses" if runtime == "copilot-sdk" else "chat-completions")
        study.write_json(
            path,
            {
                "requests": 3 if failing else 1,
                "http200": 2 if failing else 1,
                "ticketsReturned": 1,
                "ticketsReplayed": 1 if failing else 0,
                "sessionStable": True,
                "modelStable": True,
                "reasoningEffort": "none",
                "effortVerifiedRequests": 3 if failing else 1,
                "effortRejectedRequests": int(failing),
            },
        )
        yield "http://unused.invalid", path

    monkeypatch.setattr(study, "proxy", fake_proxy)
    public = tmp_path / "attempt.json"
    with pytest.raises(ValueError, match="reasoning effort"):
        study.run_attempt(study.pairs()[0], runtime, tmp_path / "work", {}, public)
    result = json.loads(public.read_bytes())
    assert result["status"] == "evidence-or-infrastructure-error"
    assert "mainRoute" not in result
    assert result["mainRouteFailure"]["verified"] is False
    assert result["mainRouteFailure"]["counters"]["effortRejectedRequests"] == 1
    assert result["modelBacked"] is True
    assert result["upstreamRequests"] == (4 if runtime == "copilot-sdk" else 3)
    assert result["quality"] is result["testPassed"] is None


def test_provider_failure_preserves_safe_status_and_parameter_without_raw_error():
    import io
    import urllib.error

    raw = json.dumps({"error": {"code": "unsupported_parameter", "param": "reasoning_effort", "message": "Unsupported parameter reasoning_effort with tools; secret-ticket-123"}}).encode()
    error = urllib.error.HTTPError("http://unused.invalid", 400, "Bad Request", {}, io.BytesIO(raw))
    result = study.provider_failure(error)
    assert result["httpStatus"] == 400
    assert result["parameter"] == "reasoning_effort"
    assert result["signals"]["unsupportedParameter"] is True
    assert result["signals"]["mentionsTools"] is True
    assert "secret-ticket" not in json.dumps(result)


@pytest.mark.parametrize("fail_at", [None, 1, 2])
def test_explicit_none_probes_are_separate_bounded_and_stop_on_first_failure(tmp_path, monkeypatch, fail_at):
    import io
    import urllib.error
    from argparse import Namespace
    from contextlib import contextmanager

    monkeypatch.setattr(study, "INPUTS", ROOT / "experiments" / "bcal-full-gold")
    current = {}
    requests = []

    @contextmanager
    def fake_proxy(_work, _env, model, wire, role, *, explicit_none_probe):
        assert explicit_none_probe
        assert model == "gpt-56-reasoning-sol"
        assert role == "HostAgent"
        current.update(wire=wire, audit=tmp_path / f"{wire}.json")
        study.write_json(current["audit"], {"requests": 0, "http200": 0, "ticketsReturned": 0, "ticketsReplayed": 0, "sessionStable": True, "modelStable": True, "explicitNoneVerifiedRequests": 0})
        yield "http://unused.invalid", current["audit"]

    def respond(request, timeout):
        body = json.loads(request.data)
        assert body["model"] == "gpt-56-reasoning-sol"
        assert body["tools"]
        assert "tool_choice" not in body
        if current["wire"] == "responses":
            assert body["reasoning"] == {"effort": "none"}
            assert "reasoning_effort" not in body
            assert body["parallel_tool_calls"] is False
            assert body["max_output_tokens"] == 1024
        else:
            assert body["reasoning_effort"] == "none"
            assert "reasoning" not in body
            assert body["max_completion_tokens"] == 16384
        requests.append(body)
        failed = len(requests) == fail_at
        study.write_json(
            current["audit"],
            {
                "requests": 1,
                "http200": int(not failed),
                "ticketsReturned": int(not failed),
                "ticketsReplayed": 0,
                "sessionStable": True,
                "modelStable": True,
                "explicitNoneVerifiedRequests": 1,
                "reasoningEffort": "none",
                "effortVerifiedRequests": 1,
                "effortRejectedRequests": 0,
            },
        )
        if failed:
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"error":{"param":"reasoning_effort"}}'))
        return io.StringIO(
            json.dumps({"status": "completed", "output": [{"type": "message"}]} if current["wire"] == "responses" else {"choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]})
        )

    monkeypatch.setattr(study, "proxy", fake_proxy)
    monkeypatch.setattr(study.urllib.request, "urlopen", respond)
    args = Namespace(work=tmp_path, output=tmp_path)
    if fail_at:
        with pytest.raises(urllib.error.HTTPError):
            study.routing_preflight(args, explicit_none_probe=True)
    else:
        study.routing_preflight(args, explicit_none_probe=True)
    receipt = json.loads((tmp_path / "explicit-none-probe.json").read_bytes())
    assert receipt["requestLimit"] == 2
    assert receipt["requests"] == len(requests) == (fail_at or 2)
    assert receipt["status"] == ("failed" if fail_at else "passed")
    assert receipt["kind"] == "explicit-none-protocol-probes-not-gold-admission"
    assert receipt["reasoningEffort"] == "none"
    assert receipt["goldAdmission"] is receipt["sdkExecution"] is receipt["stickyReplayProven"] is False
    assert receipt["semanticAttempts"] == 0
    assert not (tmp_path / "routing-preflight.json").exists()
    assert study.study()["inference"]["reasoning"] == "none"


@pytest.mark.parametrize("verified", [None, 0, True])
def test_explicit_none_receipt_requires_actual_outbound_effort_verification(tmp_path, verified):
    value = {"requests": 1, "http200": 1, "ticketsReturned": 1, "ticketsReplayed": 0, "sessionStable": True, "modelStable": True}
    if verified is not None:
        value["explicitNoneVerifiedRequests"] = verified
    path = tmp_path / "route.json"
    study.write_json(path, value)
    with pytest.raises(ValueError, match=r"Unexpected|verified"):
        study.route_receipt(path, explicit_none_probe=True)


def test_carry_forward_hold_cannot_be_ignored(tmp_path, monkeypatch):
    original = study.INPUTS
    config = study.study()
    config["budget"]["unresolvedLocalReservationSeconds"] = 180000
    (tmp_path / "symbols.json").write_bytes((original / "symbols.json").read_bytes())
    study.write_json(tmp_path / "study.json", config)
    monkeypatch.setattr(study, "INPUTS", tmp_path)
    with pytest.raises(ValueError, match="carry-forward"):
        study.study()


def test_prior_hosted_charges_cannot_be_dropped_from_the_corrected_study(tmp_path, monkeypatch):
    original = study.INPUTS
    config = study.study()
    config["budget"]["historicalMeasuredSeconds"] = config["budget"]["originalLocalMeasuredSeconds"]
    (tmp_path / "symbols.json").write_bytes((original / "symbols.json").read_bytes())
    study.write_json(tmp_path / "study.json", config)
    monkeypatch.setattr(study, "INPUTS", tmp_path)
    with pytest.raises(ValueError, match="Prior hosted charges"):
        study.study()


def test_route_receipt_rejects_missing_stickiness_and_private_fields(tmp_path):
    path = tmp_path / "route.json"
    value = {"requests": 2, "http200": 2, "ticketsReturned": 0, "ticketsReplayed": 0, "sessionStable": True, "modelStable": True}
    study.write_json(path, value)
    with pytest.raises(ValueError, match="sticky"):
        study.route_receipt(path)
    value.update(ticketsReturned=2, ticketsReplayed=1)
    study.write_json(path, value)
    assert study.route_receipt(path) == value
    value["ticket"] = "must-not-be-published"
    study.write_json(path, value)
    with pytest.raises(ValueError, match="Unexpected"):
        study.route_receipt(path)
    diagnostic = study.route_failure_diagnostics(path)
    assert diagnostic["verified"] is False
    counters = diagnostic["counters"]
    assert isinstance(counters, dict)
    assert counters["requests"] == 2
    assert value["ticket"] not in json.dumps(diagnostic)


def test_package_admission_reuses_exact_installed_action_archive(tmp_path, monkeypatch):
    import hashlib

    installed = tmp_path / "store" / "30.0" / "tools" / "net10.0" / "any" / "bcal.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"binary")
    archive = installed.parents[3] / "test.package.30.0.nupkg"
    archive.write_bytes(b"exact governed archive")
    config = {"id": "test.package", "version": "30.0", "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "bytes": archive.stat().st_size, "sourceCommitSha": "a" * 40}
    folder = tmp_path / "private"
    (folder / "stage").mkdir(parents=True)
    monkeypatch.setenv("BCAL_STUDY_INSTALLED_BINARY", str(installed))
    monkeypatch.setattr(study, "study", lambda: {"package": config})
    monkeypatch.setattr(study, "verify_package", lambda _: installed)
    assert study.prepare_package(folder)["sha256"] == config["sha256"]
    assert (folder / "package.nupkg").read_bytes() == archive.read_bytes()
    (folder / "package.nupkg").unlink()
    archive.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="archive bytes differ"):
        study.prepare_package(folder)


def test_sanitized_legacy_failure_never_exports_or_scores_success():
    transcript = {
        "executionIdentity": {"sourceCommitSha": study.study()["package"]["sourceCommitSha"]},
        "runtimeIdentity": {
            "agentRuntime": "legacy",
            "requestedPlanningMode": None,
            "planningMode": "bcal",
            "planningMechanism": "bcal-structured",
            "completionPolicy": "bcal-whole-result-review",
            "systemPromptSha256": "a" * 64,
            "toolCatalogSha256": "b" * 64,
        },
        "completed": False,
        "failure": {"message": "PRIVATE GENERATED CONTENT"},
        "export": {"success": True},
        "totals": {},
        "steps": [],
        "evidence": {"trace": {"truncated": False, "omittedEventCount": 0, "events": []}},
    }
    value = study.sanitize_row({"transcript": transcript, "error_message": "PRIVATE GENERATED CONTENT"}, "legacy")
    assert value["completed"] is False
    assert value["exported"] is False
    assert value["usage"]["promptTokens"] is None
    assert "PRIVATE" not in json.dumps(value)


def test_sdk_catalog_admission_is_bound_to_the_actual_scenario_context():
    from bcbench.agent.bcal.agent import BCalBackendConfig
    from bcbench.types import BCalAgentPlanning, BCalAgentRuntime

    config = BCalBackendConfig(agent_runtime=BCalAgentRuntime.COPILOT_SDK, agent_planning=BCalAgentPlanning.COPILOT)
    authority = study.pairs()[4]
    transcript = {
        "executionIdentity": {"sourceCommitSha": study.study()["package"]["sourceCommitSha"]},
        "runtimeIdentity": {
            **config.planning_identity(),
            "agentRuntime": "copilot-sdk",
            "sdkPackageVersion": "1.0.29",
            "sdkRuntimeVersion": "1.0.107",
            "systemPromptSha256": "a" * 64,
            "toolCatalogSha256": authority["sdkToolCatalogSha256"],
        },
    }
    row = {"transcript": transcript, "error_message": "failed"}
    safe = study.sanitize_row(row, "copilot-sdk", sdk_catalog_sha256=authority["sdkToolCatalogSha256"])
    assert safe["identityHashes"]["toolCatalogSha256"] == authority["sdkToolCatalogSha256"]
    with pytest.raises(ValueError, match="context-specific"):
        study.sanitize_row(row, "copilot-sdk", sdk_catalog_sha256=study.pairs()[6]["sdkToolCatalogSha256"])


def test_trace_projection_never_publishes_tool_payload_or_unknown_text():
    raw = {"truncated": False, "omittedEventCount": 0, "events": [{"type": "tool_started", "sequence": 1, "toolName": "PRIVATE", "arguments": {"secret": "PRIVATE"}, "inputHash": "PRIVATE"}]}
    safe = study.trace_projection({"evidence": {"trace": raw}})
    assert len(safe["events"]) == 1
    assert "PRIVATE" not in json.dumps(safe)
    raw["truncated"] = True
    assert study.trace_projection({"evidence": {"trace": raw}})["complete"] is False
    assert study.trace_projection({})["complete"] is False


def test_transport_reuses_proxy_without_loading_the_full_bench_environment():
    import subprocess
    import sys

    script = ROOT / "scripts" / "bcal_study_transport.py"
    code = f"import runpy,sys; m=runpy.run_path({str(script)!r}); assert m['load_proxy']()._handler; assert 'bcbench.agent' not in sys.modules"
    subprocess.run([sys.executable, "-I", "-S", "-c", code], check=True)


@pytest.mark.parametrize("required_effort", [None, "none"])
def test_governed_transport_resets_ticket_and_verifies_configured_effort(tmp_path, monkeypatch, required_effort):
    import sys
    from argparse import Namespace
    from contextlib import nullcontext
    from types import ModuleType, SimpleNamespace

    httpx = pytest.importorskip("httpx2")

    transport_spec = importlib.util.spec_from_file_location("smoke_transport_test", ROOT / "scripts" / "bcal_study_transport.py")
    transport = importlib.util.module_from_spec(transport_spec)
    transport_spec.loader.exec_module(transport)
    model = "gpt-56-reasoning-sol" if required_effort else "gpt-55-chat"
    observed = []
    sessions = []

    def upstream(request):
        observed.append(request.headers["x-sticky-route-session-ticket"])
        sessions.append(request.headers["X-SessionId"])
        return httpx.Response(200, headers={"x-sticky-route-session-ticket": "PRIVATE-OPAQUE"} if len(observed) == 1 else {}, json={})

    fake_api = ModuleType("bc_eval.llm.llm_api")
    settings = SimpleNamespace(environment="TEST", tenant_id="test", client_id="test")
    fake_api.ENDPOINTS = {"TEST": "https://not-called.invalid"}
    fake_api.SCOPE = "test"
    fake_api.LlmApiSettings = SimpleNamespace(from_env=lambda: settings)
    fake_api.LlmApiTransport = lambda _, inner: inner
    fake_api.httpx = httpx
    fake_api.taxonomy_headers = lambda *_args, **_kwargs: {"X-ModelType": "dev-" + model, "x-llm-models": "dev-" + model}
    for name in ("bc_eval", "bc_eval.llm"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    monkeypatch.setitem(sys.modules, "bc_eval.llm.llm_api", fake_api)
    fake_identity = ModuleType("azure.identity")
    fake_identity.CertificateCredential = lambda *_args, **_kwargs: nullcontext()
    fake_identity.get_bearer_token_provider = lambda *_: lambda: "not-a-real-token"
    monkeypatch.setitem(sys.modules, "azure.identity", fake_identity)
    monkeypatch.setattr(httpx, "HTTPTransport", lambda: httpx.MockTransport(upstream))
    monkeypatch.setenv("LLM_API_CERTIFICATE_FILE", str(tmp_path / "not-read.pfx"))
    monkeypatch.setenv("BCAL_SDK_PROXY_KEY", "local-test-only")
    monkeypatch.setenv("BCAL_AGENT_RUNTIME", "legacy")
    monkeypatch.setattr(transport, "load_proxy", lambda: SimpleNamespace(ProxyError=RuntimeError, _handler=lambda _key, _model, _wire, forward: forward))

    class Server:
        server_port = 1

        def __init__(self, _address, handler):
            self.forward = handler

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def serve_forever(self):
            for _ in range(3):
                body = {"model": model}
                if required_effort:
                    body["reasoning_effort"] = required_effort
                with self.forward("/chat/completions", body) as response:
                    response.read()
            if required_effort:
                with pytest.raises(RuntimeError, match="reasoning effort mismatch"), self.forward("/chat/completions", {"model": model}):
                    pytest.fail("Missing effort must not be forwarded.")

    monkeypatch.setattr(transport, "ThreadingHTTPServer", Server)
    transport.serve(
        Namespace(
            model=model,
            step="HostAgent",
            wire_api="chat-completions",
            audit=tmp_path / "audit.json",
            ready=tmp_path / "ready.json",
            explicit_none_probe=False,
            required_reasoning_effort=required_effort,
        )
    )
    assert observed == ["", "PRIVATE-OPAQUE", ""]
    assert len(set(sessions)) == 1
    assert "PRIVATE-OPAQUE" not in (tmp_path / "audit.json").read_text()
    diagnostics = study.legacy_diagnostic_receipt(tmp_path / "audit.diagnostics.json")
    assert diagnostics["valid"] is True
    assert "PRIVATE-OPAQUE" not in json.dumps(diagnostics)
    headers = [event for event in diagnostics["events"] if event["phase"] == "headers"]
    assert [event["requestsObserved"] for event in headers] == [1, 2, 3]
    assert all(event["httpStatus"] == 200 and event["observedAtUtc"] for event in headers)
    if required_effort:
        audit = json.loads((tmp_path / "audit.json").read_bytes())
        assert audit["requests"] == audit["effortVerifiedRequests"] == 3
        assert audit["effortRejectedRequests"] == 1
        assert diagnostics["events"][-1]["category"] == "effort_mismatch"
        with pytest.raises(ValueError, match="reasoning effort"):
            study.route_receipt(tmp_path / "audit.json", required_reasoning_effort="none")


def test_legacy_model_response_is_not_gated_on_the_native_sdk_counter():
    legacy = {"agentRuntimeEvidence": [{"modelRequests": 0}], "evidence": {"trace": {"events": [{"type": "model_response", "succeeded": True}]}}}
    assert study.model_response_observed({"http200": 8}, legacy) is True
    assert study.model_response_observed({"http200": 0}, legacy) is False
    legacy["evidence"]["trace"]["events"][0]["succeeded"] = False
    assert study.model_response_observed({"http200": 1}, legacy) is True
    assert study.model_response_observed({"http200": 1}, {"agentRuntimeEvidence": [{"modelRequests": 1}]}) is True
    assert study.model_response_observed({"http200": 1}, {"agentRuntimeEvidence": [{"modelRequests": 0}]}) is False


def test_summary_retains_missing_cells_and_refuses_complete_claim(tmp_path):
    from argparse import Namespace

    with pytest.raises(ValueError, match="incomplete"):
        study.summary(Namespace(work=tmp_path, output=tmp_path / "summary"))
    result = json.loads((tmp_path / "summary" / "comparison.json").read_bytes())
    assert result["complete"] is False
    assert result["scoreable"] == 0
    assert len(result["missing"]) == 16


def test_existing_workflow_is_the_only_dispatch_and_reuses_actions():
    caller = yaml.safe_load((ROOT / ".github" / "workflows" / "bcal-evaluation.yml").read_text())
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "bcal-governed-policy.yml").read_text())
    action = yaml.safe_load((ROOT / ".github" / "actions" / "setup-bcal-governed-study" / "action.yml").read_text())
    assert caller["jobs"]["get-entries"]["if"] == "(inputs.validation-phase == '' || inputs.validation-phase == 'ordinary') && !(inputs.llm-preflight-only || false)"
    assert workflow["jobs"]["pairs"]["strategy"]["max-parallel"] == "${{ startsWith(inputs.phase, 'full-gold') && 32 || 4 }}"
    assert (
        workflow["jobs"]["admit"]["if"]
        == "inputs.phase == 'smoke' || inputs.phase == 'full-gold' || inputs.phase == 'full-gold-repeat' || inputs.phase == 'full-gold-legacy' || inputs.phase == 'full-gold-judge'"
    )
    assert (
        workflow["jobs"]["pairs"]["if"]
        == "inputs.phase == 'smoke' || inputs.phase == 'full-gold' || inputs.phase == 'full-gold-repeat' || inputs.phase == 'full-gold-legacy' || inputs.phase == 'full-gold-judge'"
    )
    assert (
        workflow["jobs"]["summarize"]["if"]
        == "always() && (inputs.phase == 'smoke' || inputs.phase == 'full-gold' || inputs.phase == 'full-gold-repeat' || inputs.phase == 'full-gold-legacy' || inputs.phase == 'full-gold-judge')"
    )
    repeat_admission = next(step for step in workflow["jobs"]["admit"]["steps"] if step.get("id") == "gold")
    assert repeat_admission["env"]["STUDY_PHASE"] == "${{ inputs.phase }}"
    assert '"*$label $($env:STUDY_PHASE)"' in repeat_admission["run"]
    assert "runtime-proofs" in repeat_admission["run"]
    assert "$receipt.runtimeDiagnosticsProof.sha256" in repeat_admission["run"]
    package_step = next(step for step in action["runs"]["steps"] if step.get("id") == "package")
    assert package_step["run"].index("runtime-proofs") < package_step["run"].index('"version=')
    probe_step = next(step for step in workflow["jobs"]["preflight"]["steps"] if step.get("if") == "inputs.phase == 'full-gold-none-probe'")
    assert "explicit-none-probe" in probe_step["run"]
    assert not any("routing-preflight" in step.get("run", "") for step in workflow["jobs"]["preflight"]["steps"] if step.get("if") == "inputs.phase == 'full-gold-none-probe'")
    assert any(step.get("uses") == "./.github/actions/install-bcal" for step in action["runs"]["steps"])
    assert any(step.get("uses") == "./.github/actions/setup-python-uv" for step in action["runs"]["steps"])
    assert all(
        step.get("with", {}).get("path") in ("study-sanitized\\*.json", "study-summary\\*")
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
