import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("governed_study_test", ROOT / "scripts" / "bcal_governed_study.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


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
    assert study.study()["inference"]["reasoning"] is None


def test_full_gold_rejects_hidden_exclusions(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "INPUTS", ROOT / "experiments" / "bcal-full-gold")
    config = study.study()
    config["datasets"][0]["selectedEntries"].pop()
    study.write_json(tmp_path / "study.json", config)
    monkeypatch.setattr(study, "INPUTS", tmp_path)
    with pytest.raises(ValueError, match="without exclusions"):
        study.pairs()


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
        assert "reasoning_effort" not in body
        assert "reasoning" not in body
        assert body["tools"]
        if current["wire"] == "responses":
            assert body["tool_choice"] == "none"
            assert body["max_output_tokens"] == 1024
        else:
            assert set(body) == {"model", "messages", "tools", "max_completion_tokens"}
            assert body["max_completion_tokens"] == 16384
        requests.append(body)
        current["count"] += 1
        failed = len(requests) == fail_at
        count = current["count"]
        study.write_json(current["audit"], {"requests": count, "http200": count - failed, "ticketsReturned": count - failed, "ticketsReplayed": count - 1, "sessionStable": True, "modelStable": True})
        if failed:
            raise TimeoutError("simulated upstream failure")
        return io.StringIO(json.dumps({"output": []} if current["wire"] == "responses" else {"choices": []}))

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
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    if effort:
        with pytest.raises(ValueError, match="unspecified"):
            transport.bridge()
        assert not observed
    else:
        transport.bridge()
        assert observed == [{"model": body["model"], "messages": body["messages"], "tools": body["tools"], "max_completion_tokens": 16384}]


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
            {"requests": 1, "http200": int(not failed), "ticketsReturned": int(not failed), "ticketsReplayed": 0, "sessionStable": True, "modelStable": True, "explicitNoneVerifiedRequests": 1},
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
    assert study.study()["inference"]["reasoning"] is None


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


def test_governed_transport_resets_missing_response_ticket_without_persisting_it(tmp_path, monkeypatch):
    import sys
    from argparse import Namespace
    from contextlib import nullcontext
    from types import ModuleType, SimpleNamespace

    httpx = pytest.importorskip("httpx")

    transport_spec = importlib.util.spec_from_file_location("smoke_transport_test", ROOT / "scripts" / "bcal_study_transport.py")
    transport = importlib.util.module_from_spec(transport_spec)
    transport_spec.loader.exec_module(transport)
    model = "gpt-55-chat"
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
                with self.forward("/chat/completions", {"model": model}) as response:
                    response.read()

    monkeypatch.setattr(transport, "ThreadingHTTPServer", Server)
    transport.serve(Namespace(model=model, step="HostAgent", wire_api="chat-completions", audit=tmp_path / "audit.json", ready=tmp_path / "ready.json", explicit_none_probe=False))
    assert observed == ["", "PRIVATE-OPAQUE", ""]
    assert len(set(sessions)) == 1
    assert "PRIVATE-OPAQUE" not in (tmp_path / "audit.json").read_text()


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
    assert workflow["jobs"]["pairs"]["strategy"]["max-parallel"] == "${{ inputs.phase == 'full-gold' && 32 || 4 }}"
    assert workflow["jobs"]["admit"]["if"] == "inputs.phase == 'smoke' || inputs.phase == 'full-gold'"
    assert workflow["jobs"]["pairs"]["if"] == "inputs.phase == 'smoke' || inputs.phase == 'full-gold'"
    assert workflow["jobs"]["summarize"]["if"] == "always() && (inputs.phase == 'smoke' || inputs.phase == 'full-gold')"
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
