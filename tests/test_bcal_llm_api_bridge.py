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
            calls["responses_request"] = kwargs
            return calls["responses_response"]

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


@pytest.fixture
def luna_api(monkeypatch, fake_llm_api):
    monkeypatch.delenv(bc_eval_llm_api_bridge._CERT_FILE_ENV, raising=False)
    fake_llm_api["responses_response"] = {
        "id": "resp-1",
        "model": "gpt-6-luna",
        "created_at": 123,
        "status": "completed",
        "output": [
            {"id": "rs-1", "type": "reasoning", "summary": [], "encrypted_content": "opaque-reasoning"},
            {"id": "fc-1", "type": "function_call", "call_id": "call-1", "name": "lookup", "arguments": '{"name":"Customer"}', "status": "completed"},
            {"id": "fc-2", "type": "function_call", "call_id": "call-2", "name": "lookup", "arguments": '{"name":"Vendor"}', "status": "completed"},
        ],
        "usage": {
            "input_tokens": 40,
            "output_tokens": 25,
            "total_tokens": 65,
            "input_tokens_details": {"cached_tokens": 10},
            "output_tokens_details": {"reasoning_tokens": 15},
        },
    }
    return fake_llm_api


def test_model_protocol_defaults_to_chat_and_explicitly_routes_luna_to_responses():
    assert bc_eval_llm_api_bridge._protocol_for_model("gpt-6-luna") == "responses"
    assert bc_eval_llm_api_bridge._protocol_for_model("gpt-55-chat") == "chat-completions"
    assert bc_eval_llm_api_bridge._protocol_for_model("future-model") == "chat-completions"


def test_luna_uses_responses_with_reasoning_and_non_strict_tools(monkeypatch, luna_api):
    messages = [{"role": "system", "content": "Help with AL."}, {"role": "user", "content": "Look up Customer and Vendor."}]
    function = {"name": "lookup", "description": "Look up an AL object.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}}}

    completion = json.loads(_run_main(monkeypatch, {"model": "gpt-6-luna", "messages": messages, "tools": [{"type": "function", "function": function}], "max_completion_tokens": 4096}))

    assert "request" not in luna_api
    assert luna_api["responses_request"] == {
        "model": "gpt-6-luna",
        "input": messages,
        "tools": [{**function, "type": "function", "strict": False}],
        "reasoning": {"effort": "medium", "context": "current_turn"},
        "max_output_tokens": 4096,
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "extra_headers": {"x-sticky-route-session-ticket": ""},
    }
    assert completion["choices"] == [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "provider_context": {
                    "format": "bcbench.responses.v1",
                    "model": "gpt-6-luna",
                    "output": luna_api["responses_response"]["output"],
                },
                "tool_calls": [
                    {"id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": '{"name":"Customer"}'}},
                    {"id": "call-2", "type": "function", "function": {"name": "lookup", "arguments": '{"name":"Vendor"}'}},
                ],
            },
        }
    ]
    assert completion["usage"] == {
        "prompt_tokens": 40,
        "completion_tokens": 25,
        "total_tokens": 65,
        "prompt_tokens_details": {"cached_tokens": 10},
        "completion_tokens_details": {"reasoning_tokens": 15},
    }


def test_luna_uses_reasoning_effort_from_environment(monkeypatch, luna_api):
    monkeypatch.setenv(bc_eval_llm_api_bridge._REASONING_EFFORT_ENV, "high")

    _run_main(monkeypatch, {"model": "gpt-6-luna", "messages": []})

    assert luna_api["responses_request"]["reasoning"]["effort"] == "high"


def test_luna_request_reasoning_effort_overrides_environment(monkeypatch, luna_api):
    monkeypatch.setenv(bc_eval_llm_api_bridge._REASONING_EFFORT_ENV, "high")

    _run_main(monkeypatch, {"model": "gpt-6-luna", "messages": [], "reasoning_effort": "low"})

    assert luna_api["responses_request"]["reasoning"]["effort"] == "low"


@pytest.mark.parametrize("trim_history", [False, True])
def test_luna_replays_provider_context_and_parallel_calls_from_bcal_history(monkeypatch, luna_api, trim_history):
    messages: list[dict[str, object]] = [{"role": "user", "content": "Look up Customer and Vendor."}]
    completion = json.loads(_run_main(monkeypatch, {"model": "gpt-6-luna", "messages": messages}))
    output = luna_api["responses_response"]["output"]
    assistant = completion["choices"][0]["message"]
    assistant["content"] = "Tool calls requested."
    for call in assistant["tool_calls"]:
        call["function"]["arguments"] = json.dumps(json.loads(call["function"]["arguments"]), indent=2)
    messages = ([] if trim_history else messages) + [
        assistant,
        {"role": "tool", "tool_call_id": "call-1", "content": "Customer is a table."},
        {"role": "tool", "tool_call_id": "call-2", "content": "Vendor is a table."},
    ]
    luna_api["responses_response"] = {
        **luna_api["responses_response"],
        "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Both are tables."}]}],
    }

    result = json.loads(_run_main(monkeypatch, {"model": "gpt-6-luna", "messages": messages, "reasoning_effort": "high"}))

    expected_prefix = [] if trim_history else messages[:1]
    assert luna_api["responses_request"]["input"] == [
        *expected_prefix,
        *output,
        {"type": "function_call_output", "call_id": "call-1", "output": "Customer is a table."},
        {"type": "function_call_output", "call_id": "call-2", "output": "Vendor is a table."},
    ]
    assert luna_api["responses_request"]["reasoning"]["effort"] == "high"
    assert result["choices"][0]["finish_reason"] == "stop"
    assert result["choices"][0]["message"]["content"] == "Both are tables."
    assert result["choices"][0]["message"]["provider_context"] == {
        "format": "bcbench.responses.v1",
        "model": "gpt-6-luna",
        "output": luna_api["responses_response"]["output"],
    }


def test_luna_rejects_tool_call_history_without_provider_context(monkeypatch, luna_api):
    message = {
        "role": "assistant",
        "content": "Tool calls requested.",
        "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
    }

    with pytest.raises(ValueError, match="requires provider_context"):
        _run_main(monkeypatch, {"model": "gpt-6-luna", "messages": [message]})

    assert "responses_request" not in luna_api


def test_luna_rejects_provider_context_for_another_model(monkeypatch, luna_api):
    message = {
        "role": "assistant",
        "content": "Tool calls requested.",
        "tool_calls": [],
        "provider_context": {"format": "bcbench.responses.v1", "model": "other-model", "output": []},
    }

    with pytest.raises(ValueError, match="incompatible provider_context"):
        _run_main(monkeypatch, {"model": "gpt-6-luna", "messages": [message]})

    assert "responses_request" not in luna_api


def test_luna_rejects_provider_context_that_does_not_match_tool_calls(monkeypatch, luna_api):
    message = {
        "role": "assistant",
        "content": "Tool calls requested.",
        "tool_calls": [{"id": "different-call", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}],
        "provider_context": {
            "format": "bcbench.responses.v1",
            "model": "gpt-6-luna",
            "output": luna_api["responses_response"]["output"],
        },
    }

    with pytest.raises(ValueError, match="does not match"):
        _run_main(monkeypatch, {"model": "gpt-6-luna", "messages": [message]})


@pytest.mark.parametrize(
    ("status", "details"),
    [
        ("incomplete", {"reason": "max_output_tokens"}),
        ("incomplete", {"reason": "content_filter"}),
        ("failed", {"code": "server_error"}),
    ],
)
def test_luna_does_not_execute_partial_tool_calls_or_hide_failed_responses(monkeypatch, luna_api, status, details):
    luna_api["responses_response"].update(status=status, incomplete_details=details, error=details)

    with pytest.raises(RuntimeError, match="did not complete"):
        _run_main(monkeypatch, {"model": "gpt-6-luna", "messages": []})


def test_luna_rejects_missing_encrypted_reasoning(monkeypatch, luna_api):
    del luna_api["responses_response"]["output"][0]["encrypted_content"]

    with pytest.raises(RuntimeError, match="did not return encrypted reasoning"):
        _run_main(monkeypatch, {"model": "gpt-6-luna", "messages": []})


def test_luna_preserves_refusals(monkeypatch, luna_api):
    luna_api["responses_response"]["output"] = [{"type": "message", "content": [{"type": "refusal", "refusal": "I cannot help with that."}]}]

    result = json.loads(_run_main(monkeypatch, {"model": "gpt-6-luna", "messages": []}))

    assert result["choices"][0]["message"]["content"] == "I cannot help with that."
