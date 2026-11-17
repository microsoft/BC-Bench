import json
import socket
import sys
import urllib.error
import urllib.request
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bcal_startup_fixture as fixture
from bcal_reasoning_coding import AdmissionError, CodingPolicy, ProviderBudget


def denial():
    return {
        "status": "outbound-denial-active",
        "allPrograms": True,
        "allProtocols": True,
        "ipv4NonLoopbackDenied": True,
        "ipv6NonLoopbackDenied": True,
        "profilesEnabled": True,
        "externalTcpProbeBlocked": True,
        "loopbackTcpProbeAllowed": True,
        "rulesVerified": 2,
    }


@pytest.mark.parametrize("target", ["1.1.1.1", "::2", "provider.invalid"])
def test_parent_guard_blocks_external_resolution_and_connect_without_dns(target):
    with fixture.loopback_only() as counters, socket.socket() as client:
        with pytest.raises(AdmissionError):
            client.connect((target, 443))
        with pytest.raises(AdmissionError):
            client.connect_ex((target, 443))
        with pytest.raises(AdmissionError):
            socket.getaddrinfo(target, 443)
        assert counters["blockedExternalConnects"] == 3


def test_offline_native_control_uses_real_proxy_and_never_provider_boundary(tmp_path):
    policy = CodingPolicy(model=fixture.evaluation.MODELS[0], reasoning_effort="medium", auxiliary="forbid")
    budget = ProviderBudget(tmp_path / "attempts.json", 30)
    body = {"model": policy.model, "parallel_tool_calls": False, "reasoning": {"effort": "medium"}, "tools": [{"name": "one"}, {"name": "two"}]}
    with fixture.loopback_only() as counters, fixture.offline_route(policy, budget, "offline-key") as url:
        request = urllib.request.Request(url + "/v1/responses", data=json.dumps(body).encode(), headers={"Authorization": "Bearer offline-key"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
        assert error.value.code == 400
        assert b"Offline initialization boundary stop" in error.value.read()
        assert counters["blockedExternalConnects"] == 0
    assert budget.snapshot()["attempts"] == 0
    assert budget.snapshot()["routeStages"] == {"listener_ready": 1, "local_post": 1, "forward_entered": 1, "wire_validated": 1, "listener_stopped": 1}


@pytest.mark.parametrize("damage", ["rulesVerified", "allPrograms", "ipv6NonLoopbackDenied", "externalTcpProbeBlocked"])
def test_missing_os_denial_blocks_before_any_actual_cli(tmp_path, monkeypatch, damage):
    proof = denial()
    proof[damage] = 0 if damage == "rulesVerified" else False
    path = tmp_path / "denial.json"
    path.write_text(json.dumps(proof))
    monkeypatch.setattr(fixture, "load_pin", lambda: pytest.fail("Actual CLI reached before denial"))
    with pytest.raises(AdmissionError):
        fixture.run(Namespace(network_proof=path))


@pytest.mark.parametrize("native_requests", [0, 1])
def test_full_fixture_preserves_zero_request_or_offline400_boundary_without_live_route(tmp_path, monkeypatch, native_requests):
    from bcal_reasoning_package import load_pin

    pin = load_pin()
    monkeypatch.setattr(type(pin), "verify", lambda *args: 224)
    monkeypatch.setattr(fixture, "owner_admission", lambda *args: {})
    monkeypatch.setattr(fixture.shutil, "copytree", lambda *args: None)
    monkeypatch.setattr(fixture, "materialize_symbols", lambda *args: {"count": 5})
    for name in tuple(fixture.os.environ):
        if name.startswith("LLM_API_") or name in {"OPENAI_API_KEY", "AZURE_CLIENT_SECRET"}:
            monkeypatch.delenv(name)
    monkeypatch.setenv("GITHUB_SHA", "safe-source")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    path = tmp_path / "denial.json"
    path.write_text(json.dumps(denial()))
    args = Namespace(network_proof=path, output=tmp_path / "safe", work=tmp_path / "private", package=tmp_path / "package", archive=tmp_path / "archive", symbol_cache=tmp_path / "cache")

    def run_code(actual):
        assert actual.package == args.work / "worker-0" / "package"
        assert actual.private == args.work / "000-gpt-56-reasoning-sol"
        assert fixture.evaluation.provider_route == fixture.offline_route
        budget = ProviderBudget(actual.receipt.with_suffix(".attempts.json"), 30)
        with pytest.raises(AdmissionError):
            budget.send("main", {"model": pin.source}, lambda: pytest.fail("Provider dispatch reached"))
        terminal = {
            "runtimeModel": fixture.evaluation.MODELS[0],
            "runtimeAppliedEffort": "medium",
            "turns": [{"modelRequests": native_requests, "toolCalls": 0, "terminalState": "error"}],
        }
        fixture.write_json(
            actual.receipt,
            {
                "providerAttempts": 0,
                "accounting": {"events": [], "routeStages": {"local_post": native_requests, "forward_entered": native_requests, "wire_validated": native_requests}},
                "terminalEvidence": terminal,
                "auxiliaryInvocations": 0,
                "runtimeCleanupVerified": True,
                "processEvidence": {"outcome": "nonzero_exit", "exitCode": 1, "exceptionCategory": "process_exit"},
                "failureStage": "provider_accounting",
            },
        )

    monkeypatch.setattr(fixture.evaluation, "run_code", run_code)
    fixture.run(args)
    result = json.loads((args.output / "startup-fixture-summary.json").read_bytes())
    assert result["status"] == "diagnostic-complete"
    assert result["hostedZeroRequestFailureReproduced"] == (native_requests == 0)
    assert result["providerAttempts"] == result["judgeCalls"] == result["auxiliaryInvocations"] == 0
    assert not result["domainPass"]
    assert not result["rawMessagesRetained"]
