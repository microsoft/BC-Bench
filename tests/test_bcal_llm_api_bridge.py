from __future__ import annotations

import json
import sys
import types
from io import BytesIO, StringIO

import pytest

from bcbench.agent.bcal import bc_eval_llm_api_bridge


class _LlmApiClient:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, object]] = []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class _HttpError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class _ResponseHttpError(Exception):
    def __init__(self, status_code: int) -> None:
        self.response = types.SimpleNamespace(status_code=status_code)
        super().__init__(f"HTTP {status_code}")


def test_load_request_accepts_utf8_bom_from_bcal_windows_stdin():
    request = {
        "model": "gpt-55-chat-2026-04-29",
        "messages": [{"role": "user", "content": "hello"}],
        "max_completion_tokens": 128,
    }
    input_stream = BytesIO(b"\xef\xbb\xbf" + json.dumps(request).encode())

    assert bc_eval_llm_api_bridge._load_request(input_stream) == request


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (_HttpError(500), 500),
        (_ResponseHttpError(503), 503),
        (_HttpError(599), 599),
    ],
)
def test_create_completion_records_llm_api_5xx_as_infrastructure_error(monkeypatch, tmp_path, error, status_code):
    error_file = tmp_path / "llm-api-error.json"
    monkeypatch.setenv(bc_eval_llm_api_bridge._INFRASTRUCTURE_ERROR_FILE_ENV, str(error_file))

    with pytest.raises(type(error), match=f"HTTP {status_code}"):
        bc_eval_llm_api_bridge._create_completion(_LlmApiClient(error=error), {})

    assert json.loads(error_file.read_text(encoding="utf-8")) == {
        "provider": "llm_api",
        "status_code": status_code,
        "message": f"HTTP {status_code}",
    }


@pytest.mark.parametrize("status_code", [400, 401, 429])
def test_create_completion_does_not_classify_non_5xx_failures(monkeypatch, tmp_path, status_code):
    error_file = tmp_path / "llm-api-error.json"
    monkeypatch.setenv(bc_eval_llm_api_bridge._INFRASTRUCTURE_ERROR_FILE_ENV, str(error_file))

    with pytest.raises(_HttpError, match=f"HTTP {status_code}"):
        bc_eval_llm_api_bridge._create_completion(_LlmApiClient(error=_HttpError(status_code)), {})

    assert not error_file.exists()


def test_create_completion_clears_stale_infrastructure_error_after_success(monkeypatch, tmp_path):
    error_file = tmp_path / "llm-api-error.json"
    error_file.write_text("stale", encoding="utf-8")
    monkeypatch.setenv(bc_eval_llm_api_bridge._INFRASTRUCTURE_ERROR_FILE_ENV, str(error_file))
    expected = {"choices": []}

    assert bc_eval_llm_api_bridge._create_completion(_LlmApiClient(result=expected), {}) == expected
    assert not error_file.exists()


@pytest.mark.parametrize(
    ("model", "expected_temperature"),
    [
        ("gpt-56-ceres", None),
        ("gpt-56-reasoning-sol", None),
        ("gpt-55-chat-2026-04-29", 0.2),
        ("claude-opus-4-8", 0.2),
    ],
)
def test_completion_kwargs_maps_legacy_tokens_and_omits_reasoning_temperature(model, expected_temperature):
    kwargs = bc_eval_llm_api_bridge._completion_kwargs(
        {
            "max_tokens": 512,
            "temperature": 0.2,
        },
        model,
        [{"role": "user", "content": "hello"}],
    )

    assert kwargs["max_completion_tokens"] == 512
    assert "max_tokens" not in kwargs
    if expected_temperature is None:
        assert "temperature" not in kwargs
    else:
        assert kwargs["temperature"] == expected_temperature


def test_completion_kwargs_prefers_explicit_max_completion_tokens():
    kwargs = bc_eval_llm_api_bridge._completion_kwargs(
        {
            "max_completion_tokens": 256,
            "max_tokens": 512,
        },
        "gpt-56-ceres",
        [{"role": "user", "content": "hello"}],
    )

    assert kwargs["max_completion_tokens"] == 256


def test_main_uses_direct_llm_api_client_and_external_command_contract(monkeypatch):
    request = {
        "model": "gpt-55-chat-2026-04-29",
        "messages": [{"role": "user", "content": "hello"}],
        "max_completion_tokens": 256,
        "reasoning_effort": "medium",
        "temperature": 0.3,
        "tools": [{"type": "function", "function": {"name": "lookup"}}],
    }
    response = {"id": "completion-1", "choices": [{"message": {"role": "assistant", "content": "done"}}]}
    client = _LlmApiClient(result=response)
    provider_calls: list[dict[str, object]] = []

    def create_openai_compatible_client(**kwargs: object) -> _LlmApiClient:
        provider_calls.append(kwargs)
        return client

    bc_eval_package = types.ModuleType("bc_eval")
    bc_eval_package.__path__ = []
    llm_package = types.ModuleType("bc_eval.llm")
    llm_package.__path__ = []
    providers_module = types.ModuleType("bc_eval.llm.providers")
    providers_module.create_openai_compatible_client = create_openai_compatible_client  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, "bc_eval", bc_eval_package)
    monkeypatch.setitem(sys.modules, "bc_eval.llm", llm_package)
    monkeypatch.setitem(sys.modules, "bc_eval.llm.providers", providers_module)
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=BytesIO(json.dumps(request).encode())))
    stdout = StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)

    assert bc_eval_llm_api_bridge.main() == 0
    assert provider_calls == [
        {
            "provider": "llm_api",
            "taxonomy_agent": "BC-Bench",
            "taxonomy_inference_step": "BCal",
        }
    ]
    assert client.calls == [
        {
            "model": "gpt-55-chat-2026-04-29",
            "messages": request["messages"],
            "max_completion_tokens": 256,
            "tools": request["tools"],
            "reasoning_effort": "medium",
            "temperature": 0.3,
        }
    ]
    assert json.loads(stdout.getvalue()) == response
