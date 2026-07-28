"""Tests for evaluator/_capi_taxonomy.py, the taxonomy-header shim bc-eval loads for the judge path.

The module lives under evaluator/ (loaded by the isolated bceval tool env, not importable as a
bcbench package), so it is loaded here the same way bc-eval does: via importlib.exec_module.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import ClassVar

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "evaluator" / "_capi_taxonomy.py"


@pytest.fixture
def taxonomy():
    spec = importlib.util.spec_from_file_location("_capi_taxonomy_under_test", _MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def stub_capi_model(monkeypatch):
    class _StubCapiModel:
        base_params: ClassVar[dict[str, object]] = {"customer_id": "c"}

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


def _clear_env(monkeypatch, taxonomy):
    for _, env_var, _ in taxonomy._TAXONOMY_HEADERS:
        monkeypatch.delenv(env_var, raising=False)


def test_install_merges_headers_into_common_params(monkeypatch, taxonomy, stub_capi_model):
    _clear_env(monkeypatch, taxonomy)

    taxonomy.install()

    params = stub_capi_model._get_common_capi_parameters()
    assert params["headers"]["X-Taxonomy-TrafficType"] == "Test"
    assert params["headers"]["X-Taxonomy-Experience"] == "DynamicsBusinessCentral"
    assert params["customer_id"] == "c"  # existing params preserved


def test_install_is_idempotent(monkeypatch, taxonomy, stub_capi_model):
    _clear_env(monkeypatch, taxonomy)

    taxonomy.install()
    patched = stub_capi_model.__dict__["_get_common_capi_parameters"]
    taxonomy.install()

    assert stub_capi_model.__dict__["_get_common_capi_parameters"] is patched


def test_install_noop_when_bc_eval_absent(monkeypatch, taxonomy):
    _clear_env(monkeypatch, taxonomy)
    monkeypatch.setitem(sys.modules, "bc_eval", None)  # force ImportError on `import bc_eval...`

    taxonomy.install()  # must not raise
