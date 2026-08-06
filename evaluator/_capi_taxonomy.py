"""Inject the M365 LLM API headers into bc-eval's CAPI judge calls.

The nl2al ``lm_checklist`` judge runs inside the ``bceval metrics calculate`` step through
``bc_eval``'s ``CapiModel``, which (like the bcal bridge) does not send the now-required
``X-Taxonomy-*`` headers, so CAPI rejects the calls with ``InvalidInferenceInput``. bc-eval
``exec_module``s the ``--evaluator-definitions`` / ``--metric-definitions`` files (this package's
``scores.py`` and ``metrics.py``) while resolving evaluators, before any judge runs, so installing
the patch at their import time covers the judge path.

Self-contained on purpose: the ``uv tool`` env that runs ``bceval`` has ``bc_eval`` but not
``bcbench`` (which hosts the equivalent bridge-side shim), so this must not import ``bcbench``.
"""

from __future__ import annotations

import os

# (header name, env var, default value) -- kept in sync with
# src/bcbench/agent/bcal/bc_eval_capi_bridge.py::_TAXONOMY_HEADERS.
_TAXONOMY_HEADERS: tuple[tuple[str, str, str], ...] = (
    ("X-Taxonomy-Experience", "CAPI_TAXONOMY_EXPERIENCE", "AppCopilots"),
    ("X-Taxonomy-Agent", "CAPI_TAXONOMY_AGENT", "bcal"),
    ("X-Taxonomy-InferenceStep", "CAPI_TAXONOMY_INFERENCE_STEP", "ChatCompletion"),
    ("X-Taxonomy-TrafficType", "CAPI_TAXONOMY_TRAFFIC_TYPE", "OfflineEvaluation"),
)

# Match production's current zero-counter scaffold. Do not add a retry loop here: correct retry
# support also requires propagating response state and retry limits.
_RETRY_ATTEMPT = '{"bceval":0}'

_PATCH_FLAG = "_bcbench_taxonomy_patched"


def _resolve_headers() -> dict[str, str]:
    resolved: dict[str, str] = {}
    for header, env_var, default in _TAXONOMY_HEADERS:
        value = os.environ.get(env_var, default).strip()
        if value:
            resolved[header] = value
    return resolved


def install() -> None:
    headers = _resolve_headers()
    if not headers:
        return

    try:
        from bc_eval.capi.capi_model import CapiModel
    except ImportError:
        return  # No CAPI judge in this context; nothing to patch.

    get_common = getattr(CapiModel, "_get_common_capi_parameters", None)
    if get_common is None or getattr(get_common.__func__, _PATCH_FLAG, False):
        return  # Missing internal (revisit on bc-eval bump) or already patched.

    original = get_common.__func__

    def _with_taxonomy_headers(cls: type) -> dict[str, object]:
        params = original(cls)
        merged = dict(params.get("headers") or {})
        merged.update(headers)
        merged.update(
            {
                "x-llm-service-tier": os.environ.get("CAPI_SERVICE_TIER", "flex").strip() or "flex",
                "x-retry-attempt": _RETRY_ATTEMPT,
                "x-sticky-route-session-ticket": "",
                "X-SessionId": params["x_ms_correlation_id"],
                "X-InteractionId": params["x_ms_correlation_id"],
                "x-metadata-tenant-id": params["x_ms_client_tenant_id"],
            }
        )
        params["headers"] = merged
        return params

    setattr(_with_taxonomy_headers, _PATCH_FLAG, True)
    CapiModel._get_common_capi_parameters = classmethod(_with_taxonomy_headers)
