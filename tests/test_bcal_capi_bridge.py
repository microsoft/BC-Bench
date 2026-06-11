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


@pytest.fixture
def fake_capi_auth(monkeypatch):
    """Provide stubs for bc_eval.capi.capi_auth and azure.identity used by the cert patcher."""
    bc_eval_pkg = types.ModuleType("bc_eval")
    bc_eval_pkg.__path__ = []
    capi_pkg = types.ModuleType("bc_eval.capi")
    capi_pkg.__path__ = []
    capi_auth_mod = types.ModuleType("bc_eval.capi.capi_auth")
    capi_auth_mod.get_certificate_credential = lambda: "kv-credential"
    monkeypatch.setitem(sys.modules, "bc_eval", bc_eval_pkg)
    monkeypatch.setitem(sys.modules, "bc_eval.capi", capi_pkg)
    monkeypatch.setitem(sys.modules, "bc_eval.capi.capi_auth", capi_auth_mod)

    class _StubCertCredential:
        def __init__(self, tenant_id, client_id, certificate_path):
            self.tenant_id = tenant_id
            self.client_id = client_id
            self.certificate_path = certificate_path

    azure_pkg = types.ModuleType("azure")
    azure_pkg.__path__ = []
    identity_mod = types.ModuleType("azure.identity")
    identity_mod.CertificateCredential = _StubCertCredential
    monkeypatch.setitem(sys.modules, "azure", azure_pkg)
    monkeypatch.setitem(sys.modules, "azure.identity", identity_mod)

    return capi_auth_mod, _StubCertCredential


def test_maybe_install_local_cert_credential_noop_when_env_unset(monkeypatch, fake_capi_auth):
    capi_auth_mod, _ = fake_capi_auth
    monkeypatch.delenv(bc_eval_capi_bridge._CERT_FILE_ENV, raising=False)
    original = capi_auth_mod.get_certificate_credential

    bc_eval_capi_bridge._maybe_install_local_cert_credential()

    assert capi_auth_mod.get_certificate_credential is original


def test_maybe_install_local_cert_credential_raises_when_file_missing(monkeypatch, fake_capi_auth, tmp_path):
    monkeypatch.setenv(bc_eval_capi_bridge._CERT_FILE_ENV, str(tmp_path / "does-not-exist.pfx"))

    with pytest.raises(RuntimeError, match="does not exist"):
        bc_eval_capi_bridge._maybe_install_local_cert_credential()


def test_maybe_install_local_cert_credential_requires_tenant_and_client_ids(monkeypatch, fake_capi_auth, tmp_path):
    cert = tmp_path / "cert.pfx"
    cert.write_bytes(b"fake-pfx")
    monkeypatch.setenv(bc_eval_capi_bridge._CERT_FILE_ENV, str(cert))
    monkeypatch.delenv(bc_eval_capi_bridge._CERT_TENANT_ENV, raising=False)
    monkeypatch.delenv(bc_eval_capi_bridge._CERT_CLIENT_ENV, raising=False)

    with pytest.raises(RuntimeError, match="CAPI_TENANT_ID"):
        bc_eval_capi_bridge._maybe_install_local_cert_credential()


def test_maybe_install_local_cert_credential_patches_factory(monkeypatch, fake_capi_auth, tmp_path):
    capi_auth_mod, stub_cred = fake_capi_auth
    cert = tmp_path / "cert.pfx"
    cert.write_bytes(b"fake-pfx")
    monkeypatch.setenv(bc_eval_capi_bridge._CERT_FILE_ENV, str(cert))
    monkeypatch.setenv(bc_eval_capi_bridge._CERT_TENANT_ENV, "tenant-x")
    monkeypatch.setenv(bc_eval_capi_bridge._CERT_CLIENT_ENV, "client-y")

    bc_eval_capi_bridge._maybe_install_local_cert_credential()

    cred = capi_auth_mod.get_certificate_credential()
    assert isinstance(cred, stub_cred)
    assert cred.tenant_id == "tenant-x"
    assert cred.client_id == "client-y"
    assert cred.certificate_path == str(cert)

