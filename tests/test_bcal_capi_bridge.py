from __future__ import annotations

import json
import sys
import types
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bcbench.agent.bcal import bc_eval_capi_bridge


def test_load_request_accepts_utf8_bom_from_bcal_windows_stdin():
    request = {
        "model": "gpt-5",
        "messages": [{"role": "user", "content": "hello"}],
        "max_completion_tokens": 128,
    }
    input_stream = BytesIO(b"\xef\xbb\xbf" + json.dumps(request).encode())

    assert bc_eval_capi_bridge._load_request(input_stream) == request


# azure-core is only installed in the side .bcal-capi-venv used by the bridge at runtime, so we
# stub the exception type for tests that don't want to drag azure-core into the main bcbench env.
@pytest.fixture
def http_response_error(monkeypatch):
    class _StubHttpResponseError(Exception):
        def __init__(self, message=""):
            super().__init__(message)

    azure_pkg = types.ModuleType("azure")
    azure_pkg.__path__ = []  # mark as package
    core_pkg = types.ModuleType("azure.core")
    core_pkg.__path__ = []
    exceptions_mod = types.ModuleType("azure.core.exceptions")
    exceptions_mod.HttpResponseError = _StubHttpResponseError

    monkeypatch.setitem(sys.modules, "azure", azure_pkg)
    monkeypatch.setitem(sys.modules, "azure.core", core_pkg)
    monkeypatch.setitem(sys.modules, "azure.core.exceptions", exceptions_mod)
    return _StubHttpResponseError


def _stub_client(side_effect):
    create = MagicMock(side_effect=side_effect)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), create


def test_create_with_retry_recovers_from_transient_http_error(monkeypatch, http_response_error):
    monkeypatch.setattr(bc_eval_capi_bridge, "_TRANSIENT_RETRY_BACKOFF_SEC", 0.0)
    expected = {"id": "ok"}
    client, create = _stub_client([http_response_error("boom"), http_response_error("boom"), expected])

    assert bc_eval_capi_bridge._create_with_retry(client, {"model": "m", "messages": []}) is expected
    assert create.call_count == 3


def test_create_with_retry_gives_up_after_max_attempts(monkeypatch, http_response_error):
    monkeypatch.setattr(bc_eval_capi_bridge, "_TRANSIENT_RETRY_BACKOFF_SEC", 0.0)
    client, create = _stub_client(http_response_error("boom"))

    with pytest.raises(http_response_error):
        bc_eval_capi_bridge._create_with_retry(client, {"model": "m", "messages": []})

    assert create.call_count == bc_eval_capi_bridge._TRANSIENT_RETRY_ATTEMPTS
