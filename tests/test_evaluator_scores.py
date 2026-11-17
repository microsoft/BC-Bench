from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def test_lm_checklist_supplies_initial_routing_ticket(monkeypatch):
    class BuiltinLmChecklist:
        def _request_args(self, output, expected, **kwargs):
            return {"output": output, "expected": expected, **kwargs}

    module = types.ModuleType("bc_eval.scorers.autoeval.lmchecklist")
    module.LmChecklist = BuiltinLmChecklist  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    path = Path(__file__).parents[1] / "evaluator" / "scores.py"
    spec = importlib.util.spec_from_file_location("evaluator_scores", path)
    assert spec is not None
    assert spec.loader is not None
    scores = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scores)

    request_args = scores.LmChecklist()._request_args("response", {"assertions": []}, input="request")

    assert request_args == {
        "output": "response",
        "expected": {"assertions": []},
        "input": "request",
        "extra_headers": {"x-sticky-route-session-ticket": ""},
    }
