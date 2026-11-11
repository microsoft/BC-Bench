from __future__ import annotations

import io
import json
import sys
import types
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

    class _Responses:
        def create(self, **kwargs):
            calls["request"] = kwargs
            return calls["response"]

    def _create_llm_api_client(**kwargs):
        calls["client"] = kwargs
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=_Completions()), responses=_Responses())

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
        "extra_headers": {"x-sticky-route-session-ticket": "opt-out"},
        "tools": tools,
    }


def test_main_falls_back_to_bc_eval_default_credential_without_local_cert(monkeypatch, fake_llm_api):
    monkeypatch.delenv(bc_eval_llm_api_bridge._CERT_FILE_ENV, raising=False)

    _run_main(monkeypatch, {"model": "gpt-56-ceres", "messages": [], "reasoning_effort": "low"})

    assert fake_llm_api["client"]["credential"] is None
    assert fake_llm_api["request"]["reasoning_effort"] == "low"


def test_responses_round_trips_reasoning_and_parallel_tool_calls(monkeypatch, fake_llm_api):
    monkeypatch.delenv(bc_eval_llm_api_bridge._CERT_FILE_ENV, raising=False)
    output = [
        {"type": "reasoning", "id": "rs-1", "summary": [], "encrypted_content": "opaque-test-state"},
        {"type": "function_call", "id": "fc-1", "call_id": "call-1", "name": "lookup", "arguments": '{"id":1}'},
        {"type": "function_call", "id": "fc-2", "call_id": "call-2", "name": "lookup", "arguments": '{"id":2}'},
    ]
    fake_llm_api["response"] = {
        "id": "resp-1",
        "model": "gpt-5.6-sol",
        "status": "completed",
        "output": output,
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30, "output_tokens_details": {"reasoning_tokens": 12}},
    }
    request: dict[str, Any] = {
        "model": "gpt-56-reasoning-sol",
        "messages": [{"role": "user", "content": "Look up both IDs."}],
        "tools": [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}}}}],
        "reasoning_effort": "high",
        "max_completion_tokens": 1024,
    }
    completion = json.loads(_run_main(monkeypatch, request))
    assistant = completion["choices"][0]["message"]
    assert completion["choices"][0]["finish_reason"] == "tool_calls"
    assert completion["usage"]["completion_tokens_details"]["reasoning_tokens"] == 12
    assert [call["id"] for call in assistant["tool_calls"]] == ["call-1", "call-2"]
    assert assistant["provider_context"]["output"] == output
    assert fake_llm_api["request"] == {
        "model": request["model"],
        "input": request["messages"],
        "tools": [{"type": "function", "name": "lookup", "parameters": request["tools"][0]["function"]["parameters"], "strict": False}],
        "reasoning": {"effort": "high"},
        "max_output_tokens": 1024,
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "extra_headers": {"x-sticky-route-session-ticket": "opt-out"},
    }
    request["messages"].extend(
        [
            assistant,
            {"role": "tool", "tool_call_id": "call-2", "content": "second"},
            {"role": "tool", "tool_call_id": "call-1", "content": "first"},
        ]
    )
    fake_llm_api["response"]["output"] = [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Both found."}]}]
    finished = json.loads(_run_main(monkeypatch, request))
    assert fake_llm_api["request"]["input"] == [
        request["messages"][0],
        *output,
        {"type": "function_call_output", "call_id": "call-2", "output": "second"},
        {"type": "function_call_output", "call_id": "call-1", "output": "first"},
    ]
    assert finished["choices"][0]["message"]["content"] == "Both found."
    assert finished["choices"][0]["finish_reason"] == "stop"


@pytest.mark.parametrize("failure", ["missing-context", "wrong-model", "mismatched-call", "missing-result", "orphan-result"])
def test_responses_rejects_lost_or_mismatched_history(failure):
    context: dict[str, Any] = {
        "format": "bcbench.responses.v1",
        "model": "gpt-56-reasoning-sol",
        "output": [{"type": "function_call", "call_id": "call-1", "name": "noop", "arguments": "{}"}],
    }
    assistant: dict[str, object] = {"role": "assistant", "tool_calls": [{"id": "call-1"}], "provider_context": context}
    messages: list[dict[str, object]] = [assistant, {"role": "tool", "tool_call_id": "call-1", "content": "done"}]
    if failure == "missing-context":
        del assistant["provider_context"]
    elif failure == "wrong-model":
        context["model"] = "different-model"
    elif failure == "mismatched-call":
        assistant["tool_calls"] = [{"id": "different-call"}]
    elif failure == "missing-result":
        messages.pop()
    else:
        messages[1]["tool_call_id"] = "orphan-call"

    with pytest.raises(ValueError, match=r"provider_context|tool-call history|missing tool results|no matching Responses"):
        bc_eval_llm_api_bridge._responses_input(messages, "gpt-56-reasoning-sol")


@pytest.mark.parametrize(
    "response",
    [
        {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
        {"status": "completed", "output": [{"type": "reasoning", "summary": []}]},
    ],
)
def test_responses_does_not_report_incomplete_or_unreplayable_results_as_success(response):
    with pytest.raises(RuntimeError):
        bc_eval_llm_api_bridge._responses_completion(response, "gpt-56-reasoning-sol")
