from __future__ import annotations

import io
import json
import sys
import types
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import pytest

from bcbench.agent.bcal import bc_eval_llm_api_bridge


def test_load_request_accepts_utf8_bom_from_bcal_windows_stdin():
    request = {
        "model": "gpt-5",
        "messages": [{"role": "user", "content": "hello"}],
        "max_completion_tokens": 128,
    }
    input_stream = BytesIO(b"\xef\xbb\xbf" + json.dumps(request).encode())

    assert bc_eval_llm_api_bridge._load_request(input_stream) == request


class _StubCertCredential:
    def __init__(self, tenant_id, client_id, certificate_path, send_certificate_chain=False):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.certificate_path = certificate_path
        self.send_certificate_chain = send_certificate_chain


@pytest.fixture
def fake_azure_identity(monkeypatch):
    azure_pkg = types.ModuleType("azure")
    azure_pkg.__path__ = []
    identity_mod = types.ModuleType("azure.identity")
    identity_mod.CertificateCredential = _StubCertCredential  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, "azure", azure_pkg)
    monkeypatch.setitem(sys.modules, "azure.identity", identity_mod)


@pytest.fixture
def fake_llm_api(monkeypatch):
    """Stub bc_eval.llm.llm_api and record what the bridge passes to create_llm_api_client."""
    calls: dict[str, Any] = {}

    class _Settings:
        tenant_id = "tenant-x"
        client_id = "client-y"

        @classmethod
        def from_env(cls):
            return cls()

    class _Completions:
        def create(self, **kwargs):
            calls["request"] = kwargs
            return {"id": "completion-1", "choices": []}

    def _create_llm_api_client(**kwargs):
        calls["client"] = kwargs
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=_Completions()))

    modules = {name: types.ModuleType(name) for name in ("bc_eval", "bc_eval.llm", "bc_eval.llm.llm_api")}
    modules["bc_eval"].__path__ = []
    modules["bc_eval.llm"].__path__ = []
    modules["bc_eval.llm.llm_api"].LlmApiSettings = _Settings  # ty: ignore[unresolved-attribute]
    modules["bc_eval.llm.llm_api"].create_llm_api_client = _create_llm_api_client  # ty: ignore[unresolved-attribute]
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return calls


def _run_main(monkeypatch, request: dict[str, object]) -> str:
    stdin = types.SimpleNamespace(buffer=BytesIO(json.dumps(request).encode()))
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    assert bc_eval_llm_api_bridge.main() == 0
    return stdout.getvalue()


def test_local_certificate_credential_is_none_when_env_unset(monkeypatch):
    monkeypatch.delenv(bc_eval_llm_api_bridge._CERT_FILE_ENV, raising=False)

    assert bc_eval_llm_api_bridge._local_certificate_credential("tenant-x", "client-y") is None


def test_local_certificate_credential_raises_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setenv(bc_eval_llm_api_bridge._CERT_FILE_ENV, str(tmp_path / "does-not-exist.pfx"))

    with pytest.raises(RuntimeError, match="does not exist"):
        bc_eval_llm_api_bridge._local_certificate_credential("tenant-x", "client-y")


def test_local_certificate_credential_uses_sni_auth(monkeypatch, fake_azure_identity, tmp_path):
    cert = tmp_path / "cert.pfx"
    cert.write_bytes(b"fake-pfx")
    monkeypatch.setenv(bc_eval_llm_api_bridge._CERT_FILE_ENV, str(cert))

    credential = bc_eval_llm_api_bridge._local_certificate_credential("tenant-x", "client-y")

    assert isinstance(credential, _StubCertCredential)
    assert credential.tenant_id == "tenant-x"
    assert credential.client_id == "client-y"
    assert credential.certificate_path == str(cert)
    # SNI (x5c) auth is required by the app registration; without it AAD returns AADSTS700027.
    assert credential.send_certificate_chain is True


def test_main_passes_local_certificate_credential_to_llm_api_client(monkeypatch, fake_azure_identity, fake_llm_api, tmp_path):
    cert = tmp_path / "cert.pfx"
    cert.write_bytes(b"fake-pfx")
    monkeypatch.setenv(bc_eval_llm_api_bridge._CERT_FILE_ENV, str(cert))
    tools = [{"type": "function", "function": {"name": "noop"}}]

    stdout = _run_main(monkeypatch, {"model": "gpt-56-ceres", "messages": [{"role": "user", "content": "hi"}], "tools": tools})

    assert json.loads(stdout) == {"id": "completion-1", "choices": []}
    credential = fake_llm_api["client"]["credential"]
    assert isinstance(credential, _StubCertCredential)
    assert (credential.tenant_id, credential.client_id) == ("tenant-x", "client-y")
    assert fake_llm_api["client"]["inference_step"] == "HostAgent"
    assert fake_llm_api["request"] == {
        "model": "gpt-56-ceres",
        "messages": [{"role": "user", "content": "hi"}],
        "max_completion_tokens": 16384,
        "tools": tools,
        "reasoning_effort": "none",
        "extra_headers": {"x-sticky-route-session-ticket": ""},
    }


def test_main_falls_back_to_bc_eval_default_credential_without_local_cert(monkeypatch, fake_llm_api):
    monkeypatch.delenv(bc_eval_llm_api_bridge._CERT_FILE_ENV, raising=False)

    _run_main(monkeypatch, {"model": "gpt-56-ceres", "messages": [], "reasoning_effort": "low"})

    assert fake_llm_api["client"]["credential"] is None
    assert fake_llm_api["request"]["reasoning_effort"] == "low"


def test_main_disables_reasoning_when_function_tools_are_present(monkeypatch, fake_llm_api):
    tools = [{"type": "function", "function": {"name": "noop"}}]

    _run_main(monkeypatch, {"model": "gpt-56-reasoning-sol", "messages": [], "tools": tools, "reasoning_effort": "high"})

    assert fake_llm_api["request"]["reasoning_effort"] == "none"


@pytest.mark.parametrize("model", ["gpt-55-chat", "gpt-56-reasoning-sol"])
def test_main_sends_empty_routing_ticket_without_local_certificate(monkeypatch, fake_llm_api, model):
    monkeypatch.delenv(bc_eval_llm_api_bridge._CERT_FILE_ENV, raising=False)

    _run_main(monkeypatch, {"model": model, "messages": []})

    assert fake_llm_api["request"]["extra_headers"] == {"x-sticky-route-session-ticket": ""}


@pytest.mark.parametrize("effort", ["none", "high"])
def test_configured_bridge_preserves_explicit_effort_without_transport_capture(monkeypatch, fake_llm_api, tmp_path, effort):
    @dataclass
    class Settings:
        tenant_id: str = "tenant"
        client_id: str = "client"
        environment: str = "TEST"
        service_tier: str = "flex"

        @classmethod
        def from_env(cls):
            return cls()

    calls = []
    settings = []
    response = {"model": "served-model", "choices": [{"finish_reason": "stop"}]}

    def create(**kwargs):
        calls.append(kwargs)
        return response

    def create_client(**kwargs):
        settings.append(kwargs["settings"])
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))

    module = sys.modules["bc_eval.llm.llm_api"]
    monkeypatch.setattr(module, "LlmApiSettings", Settings)
    monkeypatch.setattr(
        module,
        "create_llm_api_client",
        create_client,
    )
    monkeypatch.setattr(bc_eval_llm_api_bridge, "version", lambda _: "0.10.1")
    monkeypatch.delenv(bc_eval_llm_api_bridge._CERT_FILE_ENV, raising=False)
    request = {"model": "test-model", "messages": [{"role": "user", "content": "Hello"}], "tools": [{"type": "function", "function": {"name": "sample"}}]}
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"model": "test-model", "bc_eval_version": "0.10.1", "environment": "PROD", "reasoning_effort": effort}), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=BytesIO(json.dumps(request).encode())))
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    assert bc_eval_llm_api_bridge.main(["--config", str(config)]) == 0
    assert len(calls) == 1
    assert calls[0]["reasoning_effort"] == effort
    assert calls[0]["extra_headers"] == {"x-sticky-route-session-ticket": ""}
    assert calls[0]["tools"] == request["tools"]
    assert json.loads(stdout.getvalue()) == response
    assert settings[0].environment == "PROD"
    assert list(tmp_path.iterdir()) == [config]


def test_configured_bridge_rejects_transport_version_before_request(monkeypatch, fake_llm_api, tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"bc_eval_version": "0.10.1"}', encoding="utf-8")
    monkeypatch.setattr(bc_eval_llm_api_bridge, "version", lambda _: "0.6.1")
    with pytest.raises(ValueError, match="selected transport"):
        bc_eval_llm_api_bridge.main(["--config", str(config)])
    assert not fake_llm_api
