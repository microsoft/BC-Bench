from __future__ import annotations

import json
import sys
import types
from io import BytesIO
from typing import ClassVar

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


@pytest.fixture
def fake_capi_auth(monkeypatch):
    """Provide stubs for bc_eval.capi.capi_auth and azure.identity used by the cert patcher."""

    def _original_get_certificate_credential():
        return "kv-credential"

    bc_eval_pkg = types.ModuleType("bc_eval")
    bc_eval_pkg.__path__ = []
    capi_pkg = types.ModuleType("bc_eval.capi")
    capi_pkg.__path__ = []
    capi_auth_mod = types.ModuleType("bc_eval.capi.capi_auth")
    capi_auth_mod.get_certificate_credential = _original_get_certificate_credential  # ty: ignore[unresolved-attribute]
    # Simulate `from .capi_auth import get_certificate_credential` performed at
    # import time by capi_model — this is the binding that previously stayed
    # un-patched and caused the production failure.
    capi_model_mod = types.ModuleType("bc_eval.capi.capi_model")
    capi_model_mod.get_certificate_credential = _original_get_certificate_credential  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, "bc_eval", bc_eval_pkg)
    monkeypatch.setitem(sys.modules, "bc_eval.capi", capi_pkg)
    monkeypatch.setitem(sys.modules, "bc_eval.capi.capi_auth", capi_auth_mod)
    monkeypatch.setitem(sys.modules, "bc_eval.capi.capi_model", capi_model_mod)

    class _StubCertCredential:
        def __init__(self, tenant_id, client_id, certificate_path, send_certificate_chain=False):
            self.tenant_id = tenant_id
            self.client_id = client_id
            self.certificate_path = certificate_path
            self.send_certificate_chain = send_certificate_chain

    azure_pkg = types.ModuleType("azure")
    azure_pkg.__path__ = []
    identity_mod = types.ModuleType("azure.identity")
    identity_mod.CertificateCredential = _StubCertCredential  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, "azure", azure_pkg)
    monkeypatch.setitem(sys.modules, "azure.identity", identity_mod)

    return capi_auth_mod, capi_model_mod, _StubCertCredential


def test_maybe_install_local_cert_credential_noop_when_env_unset(monkeypatch, fake_capi_auth):
    capi_auth_mod, _, _ = fake_capi_auth
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
    capi_auth_mod, capi_model_mod, stub_cred = fake_capi_auth
    cert = tmp_path / "cert.pfx"
    cert.write_bytes(b"fake-pfx")
    monkeypatch.setenv(bc_eval_capi_bridge._CERT_FILE_ENV, str(cert))
    monkeypatch.setenv(bc_eval_capi_bridge._CERT_TENANT_ENV, "tenant-x")
    monkeypatch.setenv(bc_eval_capi_bridge._CERT_CLIENT_ENV, "client-y")

    bc_eval_capi_bridge._maybe_install_local_cert_credential()

    # Patch must reach both the definition module AND every module that did
    # `from .capi_auth import get_certificate_credential` at import time -
    # capi_model is the one that bit us in production.
    for mod in (capi_auth_mod, capi_model_mod):
        cred = mod.get_certificate_credential()
        assert isinstance(cred, stub_cred), f"{mod.__name__} still holds the original credential factory"
        assert cred.tenant_id == "tenant-x"
        assert cred.client_id == "client-y"
        assert cred.certificate_path == str(cert)
        # SNI (x5c) auth is required by the CAPI app registration; without it
        # AAD rejects the client assertion with AADSTS700027.
        assert cred.send_certificate_chain is True


@pytest.fixture
def stub_capi_model(monkeypatch):
    """Stub bc_eval.capi.capi_model.CapiModel with the internal the taxonomy shim patches."""

    class _StubCapiModel:
        base_params: ClassVar[dict[str, object]] = {
            "customer_id": "c",
            "x_ms_correlation_id": "corr",
            "x_ms_client_tenant_id": "tenant",
        }

        @classmethod
        def _get_common_capi_parameters(cls) -> dict[str, object]:
            return dict(cls.base_params)

    bc_eval_pkg = types.ModuleType("bc_eval")
    bc_eval_pkg.__path__ = []
    capi_pkg = types.ModuleType("bc_eval.capi")
    capi_pkg.__path__ = []
    capi_model_mod = types.ModuleType("bc_eval.capi.capi_model")
    capi_model_mod.CapiModel = _StubCapiModel  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, "bc_eval", bc_eval_pkg)
    monkeypatch.setitem(sys.modules, "bc_eval.capi", capi_pkg)
    monkeypatch.setitem(sys.modules, "bc_eval.capi.capi_model", capi_model_mod)
    return _StubCapiModel


def _clear_taxonomy_env(monkeypatch):
    for _, env_var, _ in bc_eval_capi_bridge._TAXONOMY_HEADERS:
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.delenv("CAPI_SERVICE_TIER", raising=False)


def test_resolve_taxonomy_headers_uses_defaults(monkeypatch):
    _clear_taxonomy_env(monkeypatch)

    assert bc_eval_capi_bridge._resolve_taxonomy_headers() == {
        "X-Taxonomy-Experience": "AppCopilots",
        "X-Taxonomy-Agent": "bcal",
        "X-Taxonomy-InferenceStep": "ChatCompletion",
        "X-Taxonomy-TrafficType": "OfflineEvaluation",
    }


def test_resolve_taxonomy_headers_env_override_and_blank_dropped(monkeypatch):
    _clear_taxonomy_env(monkeypatch)
    monkeypatch.setenv("CAPI_TAXONOMY_EXPERIENCE", "MyExperience")
    monkeypatch.setenv("CAPI_TAXONOMY_TRAFFIC_TYPE", "OnlineEvaluation")
    monkeypatch.setenv("CAPI_TAXONOMY_AGENT", "   ")  # blank -> dropped

    headers = bc_eval_capi_bridge._resolve_taxonomy_headers()

    assert headers["X-Taxonomy-Experience"] == "MyExperience"
    assert headers["X-Taxonomy-TrafficType"] == "OnlineEvaluation"
    assert headers["X-Taxonomy-InferenceStep"] == "ChatCompletion"  # still the default
    assert "X-Taxonomy-Agent" not in headers


def test_install_taxonomy_headers_merges_into_common_params(monkeypatch, stub_capi_model):
    _clear_taxonomy_env(monkeypatch)

    bc_eval_capi_bridge._install_taxonomy_headers()

    params = stub_capi_model._get_common_capi_parameters()
    assert params["headers"] == {
        "X-Taxonomy-Experience": "AppCopilots",
        "X-Taxonomy-Agent": "bcal",
        "X-Taxonomy-InferenceStep": "ChatCompletion",
        "X-Taxonomy-TrafficType": "OfflineEvaluation",
        "x-llm-service-tier": "flex",
        "x-retry-attempt": '{"bceval":0}',
        "x-sticky-route-session-ticket": "",
        "X-SessionId": "corr",
        "X-InteractionId": "corr",
        "x-metadata-tenant-id": "tenant",
    }
    assert "x-llm-models" not in params["headers"]
    assert params["customer_id"] == "c"  # existing params preserved


def test_install_taxonomy_headers_preserves_existing_headers(monkeypatch, stub_capi_model):
    _clear_taxonomy_env(monkeypatch)
    stub_capi_model.base_params["headers"] = {"X-Existing": "1"}

    bc_eval_capi_bridge._install_taxonomy_headers()

    params = stub_capi_model._get_common_capi_parameters()
    assert params["headers"]["X-Existing"] == "1"
    assert params["headers"]["X-Taxonomy-TrafficType"] == "OfflineEvaluation"


def test_install_taxonomy_headers_noop_when_all_blank(monkeypatch, stub_capi_model):
    for _, env_var, _ in bc_eval_capi_bridge._TAXONOMY_HEADERS:
        monkeypatch.setenv(env_var, "")
    original = stub_capi_model.__dict__["_get_common_capi_parameters"]

    bc_eval_capi_bridge._install_taxonomy_headers()

    assert stub_capi_model.__dict__["_get_common_capi_parameters"] is original
    assert "headers" not in stub_capi_model._get_common_capi_parameters()


def test_install_taxonomy_headers_raises_when_internal_missing(monkeypatch, stub_capi_model):
    _clear_taxonomy_env(monkeypatch)
    delattr(stub_capi_model, "_get_common_capi_parameters")

    with pytest.raises(RuntimeError, match="_get_common_capi_parameters is missing"):
        bc_eval_capi_bridge._install_taxonomy_headers()
