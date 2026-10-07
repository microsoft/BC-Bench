from __future__ import annotations

import sys
import types
from typing import cast

import pytest

from evaluator import scores


@pytest.mark.parametrize(
    ("model", "expected_content", "expects_temperature"),
    [
        (
            "gpt-56-reasoning-nano-luna",
            [{"type": "output_text", "text": "answer"}],
            False,
        ),
        ("gpt-41-2025-04-14", "answer", True),
    ],
)
def test_lm_checklist_adapts_only_luna_responses_payload(
    monkeypatch,
    model,
    expected_content,
    expects_temperature,
):
    class _BuiltInLmChecklist:
        def _request_args(self, output, expected, **kwargs):
            return {
                "model": model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": "instructions"},
                    {"role": "user", "content": "question"},
                    {"role": "assistant", "content": output},
                ],
            }

    module = types.ModuleType("bc_eval.scorers.autoeval.lmchecklist")
    module.LmChecklist = _BuiltInLmChecklist  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, module.__name__, module)

    scorer = cast(_BuiltInLmChecklist, scores.LmChecklist())
    request = scorer._request_args("answer", {"assertions": []})

    assert isinstance(scorer, _BuiltInLmChecklist)
    assert request["messages"] == [
        {"role": "system", "content": "instructions"},
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "content": expected_content,
        },
    ]
    assert ("temperature" in request) is expects_temperature
